safe_weighted_mean <- function(values, weights) {
  valid <- !is.na(values) & !is.na(weights) & weights > 0
  if (!any(valid)) {
    return(NA_real_)
  }
  sum(values[valid] * weights[valid]) / sum(weights[valid])
}

detect_scheduler_profile <- function(group) {
  group <- dplyr::coalesce(as.character(group), "")
  is_batch <- grepl("^Batch", group, ignore.case = TRUE)
  rightsizing_enabled <- grepl("Predv", group, ignore.case = TRUE)

  provisioning_policy <- dplyr::case_when(
    grepl("SpotFirst", group, ignore.case = TRUE) ~ "Spot first, then on-demand",
    grepl("Spot", group, ignore.case = TRUE) ~ "Spot",
    grepl("OnD", group, ignore.case = TRUE) ~ "On-demand",
    TRUE ~ ""
  )

  dplyr::tibble(
    scheduler_mode = dplyr::if_else(is_batch, "AWS Batch", "Seqera Scheduler"),
    rightsizing_mode = dplyr::if_else(rightsizing_enabled, "Predv1", "None"),
    rightsizing_enabled = rightsizing_enabled,
    packing_enabled = !is_batch,
    provisioning_policy = provisioning_policy
  )
}

positive_gap <- function(upper, lower) {
  dplyr::if_else(
    is.na(upper) | is.na(lower),
    NA_real_,
    pmax(upper - lower, 0)
  )
}

compute_scheduler_booked <- function(capacity, efficiency_pct, fallback = NA_real_) {
  booked_from_capacity <- dplyr::if_else(
    !is.na(capacity) & !is.na(efficiency_pct),
    pmin(capacity, pmax(0, capacity * efficiency_pct / 100)),
    NA_real_
  )

  fallback <- dplyr::if_else(is.na(fallback), NA_real_, pmax(fallback, 0))
  dplyr::coalesce(booked_from_capacity, fallback)
}

parse_machine_percent <- function(x) {
  if (is.numeric(x)) {
    return(as.numeric(x))
  }
  as.numeric(gsub("%", "", x))
}

parse_machine_memory_gib <- function(x) {
  if (is.numeric(x)) {
    return(as.numeric(x))
  }
  as.numeric(stringr::str_extract(x, "[0-9.]+"))
}

compute_task_run_metrics <- function(task_data) {
  if (nrow(task_data) == 0) {
    return(data.frame())
  }

  task_data %>%
    dplyr::mutate(
      cpus = as.numeric(cpus),
      pcpu = as.numeric(pcpu),
      realtime_hours = as.numeric(realtime) / 1000 / 3600,
      requested_memory_gib_raw = dplyr::coalesce(requested_memory_gib_raw, 0),
      rss_gib_raw = dplyr::coalesce(rss_gib_raw, 0)
    ) %>%
    dplyr::group_by(run_id, pipeline) %>%
    dplyr::summarise(
      task_runtime_ms = sum(runtime_mins, na.rm = TRUE) * 60 * 1000,
      requestedCpuH = sum(cpus * realtime_hours, na.rm = TRUE),
      requestedMemGibH = sum(requested_memory_gib_raw * realtime_hours, na.rm = TRUE),
      realCpuH = sum((pcpu / 100) * realtime_hours, na.rm = TRUE),
      realMemGibH = sum(rss_gib_raw * realtime_hours, na.rm = TRUE),
      .groups = "drop"
    ) %>%
    dplyr::mutate(
      cpuEfficiency_calc = dplyr::if_else(requestedCpuH > 0, realCpuH / requestedCpuH * 100, NA_real_),
      memoryEfficiency_calc = dplyr::if_else(requestedMemGibH > 0, realMemGibH / requestedMemGibH * 100, NA_real_)
    )
}

summarise_machine_metrics <- function(machine_data, run_lookup, task_run_metrics) {
  if (nrow(machine_data) == 0) {
    return(data.frame())
  }

  machine_data <- machine_data %>%
    dplyr::left_join(run_lookup, by = "run_id")

  run_profiles <- run_lookup %>%
    dplyr::distinct(run_id, pipeline, group)
  run_profiles <- dplyr::bind_cols(run_profiles, detect_scheduler_profile(run_profiles$group))

  if ("instance_id" %in% names(machine_data)) {
    scheduler_summary <- machine_data %>%
      dplyr::mutate(
        machine_id = instance_id,
        vcpus = as.numeric(vcpus),
        memory_gib = parse_machine_memory_gib(memory),
        avg_cpu_utilization = parse_machine_percent(avg_cpu_utilization),
        avg_memory_utilization = parse_machine_percent(avg_memory_utilization),
        start_time = as.POSIXct(start_time, tz = "UTC"),
        stop_time = as.POSIXct(stop_time, tz = "UTC"),
        machine_hours = pmax(as.numeric(difftime(stop_time, start_time, units = "hours")), 0)
      ) %>%
      dplyr::group_by(run_id, pipeline) %>%
      dplyr::summarise(
        nMachines = dplyr::n_distinct(machine_id),
        vmCpuH = sum(vcpus * machine_hours, na.rm = TRUE),
        vmMemGibH = sum(memory_gib * machine_hours, na.rm = TRUE),
        schedAllocCpuEfficiency = safe_weighted_mean(avg_cpu_utilization, vcpus * machine_hours),
        schedAllocMemEfficiency = safe_weighted_mean(avg_memory_utilization, memory_gib * machine_hours),
        .groups = "drop"
      )
  } else if ("ecs_instance_id" %in% names(machine_data)) {
    scheduler_summary <- machine_data %>%
      dplyr::mutate(
        machine_id = ecs_instance_id,
        total_vcpu_hours = as.numeric(total_vcpu_hours),
        total_memory_gib_hours = as.numeric(total_memory_gib_hours),
        requested_vcpu_hours = dplyr::coalesce(as.numeric(total_requested_vcpu_hours), as.numeric(requested_vcpu_hours)),
        requested_memory_gib_hours = dplyr::coalesce(as.numeric(total_requested_memory_gib_hours), as.numeric(requested_memory_gib_hours))
      ) %>%
      dplyr::group_by(run_id, pipeline) %>%
      dplyr::summarise(
        nMachines = dplyr::n_distinct(machine_id),
        vmCpuH = sum(total_vcpu_hours, na.rm = TRUE),
        vmMemGibH = sum(total_memory_gib_hours, na.rm = TRUE),
        requestedVmCpuH = sum(requested_vcpu_hours, na.rm = TRUE),
        requestedVmMemGibH = sum(requested_memory_gib_hours, na.rm = TRUE),
        .groups = "drop"
      ) %>%
      dplyr::mutate(
        schedAllocCpuEfficiency = dplyr::if_else(vmCpuH > 0, requestedVmCpuH / vmCpuH * 100, NA_real_),
        schedAllocMemEfficiency = dplyr::if_else(vmMemGibH > 0, requestedVmMemGibH / vmMemGibH * 100, NA_real_)
      )
  } else {
    warning("Machine metrics CSV detected, but its schema is not recognized. Skipping VM metrics.")
    return(data.frame())
  }

  scheduler_summary %>%
    dplyr::left_join(run_profiles %>% dplyr::select(-group), by = c("run_id", "pipeline")) %>%
    dplyr::left_join(
      task_run_metrics %>%
        dplyr::select(run_id, pipeline, realCpuH, realMemGibH, requestedCpuH, requestedMemGibH),
      by = c("run_id", "pipeline")
    ) %>%
    dplyr::mutate(
      requestedVmCpuEfficiency = dplyr::if_else(vmCpuH > 0, requestedCpuH / vmCpuH * 100, NA_real_),
      requestedVmMemEfficiency = dplyr::if_else(vmMemGibH > 0, requestedMemGibH / vmMemGibH * 100, NA_real_),
      schedulerBookedCpuH = dplyr::if_else(
        !is.na(rightsizing_enabled) & !rightsizing_enabled & !is.na(requestedCpuH),
        pmax(requestedCpuH, 0),
        compute_scheduler_booked(vmCpuH, schedAllocCpuEfficiency, requestedCpuH)
      ),
      schedulerBookedMemGibH = dplyr::if_else(
        !is.na(rightsizing_enabled) & !rightsizing_enabled & !is.na(requestedMemGibH),
        pmax(requestedMemGibH, 0),
        compute_scheduler_booked(vmMemGibH, schedAllocMemEfficiency, requestedMemGibH)
      ),
      schedulerRightsizedCpuH = positive_gap(requestedCpuH, schedulerBookedCpuH),
      schedulerRightsizedMemGibH = positive_gap(requestedMemGibH, schedulerBookedMemGibH),
      schedulerOverbookCpuH = positive_gap(schedulerBookedCpuH, realCpuH),
      schedulerOverbookMemGibH = positive_gap(schedulerBookedMemGibH, realMemGibH),
      vmPackingSlackCpuH = positive_gap(vmCpuH, schedulerBookedCpuH),
      vmPackingSlackMemGibH = positive_gap(vmMemGibH, schedulerBookedMemGibH),
      realVmCpuEfficiency = dplyr::if_else(vmCpuH > 0, realCpuH / vmCpuH * 100, NA_real_),
      realVmMemEfficiency = dplyr::if_else(vmMemGibH > 0, realMemGibH / vmMemGibH * 100, NA_real_)
    )
}
