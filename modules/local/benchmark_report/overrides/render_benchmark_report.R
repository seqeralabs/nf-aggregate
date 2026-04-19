#!/usr/bin/env Rscript

suppressPackageStartupMessages({
  library(data.table)
  library(dplyr)
  library(jsonlite)
  library(lubridate)
  library(stringr)
  library(tidyr)
})

parse_args <- function(args) {
  parsed <- list(
    log_csv = NULL,
    output = "benchmark_report.html",
    aws_cost = NULL,
    remove_failed_tasks = FALSE
  )

  i <- 1
  while (i <= length(args)) {
    arg <- args[[i]]
    if (!startsWith(arg, "--")) {
      stop(sprintf("Unexpected positional argument: %s", arg))
    }

    key <- sub("^--", "", arg)
    if (key %in% c("remove_failed_tasks", "remove-failed-tasks")) {
      parsed$remove_failed_tasks <- TRUE
      i <- i + 1
      next
    }

    if (i == length(args)) {
      stop(sprintf("Missing value for --%s", key))
    }

    value <- args[[i + 1]]
    switch(
      key,
      "log_csv" = parsed$log_csv <- value,
      "log-csv" = parsed$log_csv <- value,
      "output" = parsed$output <- value,
      "aws_cost" = parsed$aws_cost <- value,
      "aws-cost" = parsed$aws_cost <- value,
      stop(sprintf("Unknown argument: --%s", key))
    )
    i <- i + 2
  }

  if (is.null(parsed$log_csv) || parsed$log_csv == "") {
    stop("--log_csv is required")
  }

  parsed
}

remove_prefixes <- function(names) {
  prefixes <- c(
    "service_info\\.",
    "workflow_launch\\.",
    "workflow_load\\.",
    "workflow_metadata\\.",
    "workflow\\."
  )
  pattern <- paste0("^(", paste(prefixes, collapse = "|"), ")")
  gsub(pattern, "", names)
}

first_present <- function(df, candidates, default = NA) {
  for (candidate in candidates) {
    if (candidate %in% names(df)) {
      return(df[[candidate]])
    }
  }
  rep(default, nrow(df))
}

clean_scalar_chr <- function(x) {
  x <- as.character(x)
  x[is.na(x)] <- ""
  x
}

safe_sd <- function(x) {
  if (sum(!is.na(x)) <= 1) {
    return(NA_real_)
  }
  sd(x, na.rm = TRUE)
}

build_workspace_run_url <- function(run_id, group, existing_url = "") {
  existing_url <- clean_scalar_chr(existing_url)
  group <- clean_scalar_chr(group)

  base_url <- dplyr::if_else(
    grepl("^Batch", group, ignore.case = TRUE),
    "https://seqera.io/orgs/scidev/workspaces/testing/watch",
    "https://cloud.dev-seqera.io/orgs/unified-compute/workspaces/sched-testing"
  )

  has_watch <- grepl("/watch/?$", base_url)
  run_path <- ifelse(has_watch, paste0("/", run_id), paste0("/watch/", run_id))
  fallback_url <- paste0(sub("/$", "", base_url), run_path)

  dplyr::if_else(
    nzchar(existing_url) & !grepl("example\\.invalid", existing_url, ignore.case = TRUE),
    existing_url,
    fallback_url
  )
}

build_cost_table <- function(task_data, merged_logs, aws_cost = NULL, remove_failed_tasks = FALSE) {
  accurate_task_costs <- data.frame()
  run_group_lookup <- merged_logs %>%
    distinct(run_id, group)

  if (!"group" %in% names(task_data)) {
    task_data <- task_data %>%
      left_join(run_group_lookup, by = "run_id")
  } else {
    task_data <- task_data %>%
      left_join(run_group_lookup, by = "run_id", suffix = c("", "_run")) %>%
      mutate(group = coalesce(na_if(as.character(group), ""), as.character(group_run))) %>%
      select(-any_of("group_run"))
  }

  if (!is.null(aws_cost) && !is.na(aws_cost) && aws_cost != "") {
    suppressPackageStartupMessages(library(arrow))

    core_aws_cur_cols <- c(
      "identity_line_item_id",
      "line_item_usage_type",
      "split_line_item_split_cost",
      "split_line_item_unused_cost",
      "line_item_blended_cost",
      "resource_tags"
    )

    aws_cost_table <- read_parquet(aws_cost)
    if ("resource_tags" %in% names(aws_cost_table)) {
      aws_cost_table <- reformat_cur2_0(
        aws_cost_table,
        run_ids = unique(merged_logs$run_id),
        run_id_col = "resource_tags_user_unique_run_id"
      )
      core_aws_cur_cols <- core_aws_cur_cols[!core_aws_cur_cols %in% "resource_tags"]
    }

    required_tags <- c(
      "resource_tags_user_unique_run_id",
      "resource_tags_user_pipeline_process",
      "resource_tags_user_task_hash"
    )
    core_aws_cur_cols <- c(core_aws_cur_cols, required_tags)

    accurate_task_costs <- aws_cost_table %>%
      select(all_of(core_aws_cur_cols)) %>%
      mutate(
        cost = split_line_item_split_cost + split_line_item_unused_cost,
        used_cost = split_line_item_split_cost,
        unused_cost = split_line_item_unused_cost,
        run_id = resource_tags_user_unique_run_id,
        process = resource_tags_user_pipeline_process,
        hash = substr(resource_tags_user_task_hash, 1, 8)
      ) %>%
      left_join(merged_logs %>% select(run_id, group, pipeline), by = "run_id") %>%
      group_by(run_id, pipeline, group, process, hash) %>%
      summarise(
        cost = sum(cost, na.rm = TRUE),
        used_cost = sum(used_cost, na.rm = TRUE),
        unused_cost = sum(unused_cost, na.rm = TRUE),
        .groups = "drop"
      )
  }

  if ("cost" %in% names(task_data)) {
    estim_task_costs <- task_data %>%
      select(run_id, pipeline, group, process, cost, hash) %>%
      mutate(hash = gsub("/", "", hash))
  } else {
    estim_task_costs <- task_data %>%
      select(run_id, pipeline, group, process, hash) %>%
      mutate(
        hash = gsub("/", "", hash),
        cost = NA_real_
      )
  }

  cost_table <- if (nrow(accurate_task_costs) > 0) accurate_task_costs else estim_task_costs

  if (remove_failed_tasks && nrow(cost_table) > 0) {
    task_status <- task_data %>%
      transmute(run_id, hash = gsub("/", "", hash), status)
    cost_table <- cost_table %>%
      left_join(task_status, by = c("run_id", "hash")) %>%
      filter(status == "COMPLETED") %>%
      select(-status)
  }

  cost_table
}

args <- parse_args(commandArgs(trailingOnly = TRUE))

source("benchmark_functions.R")
for (file in list.files("functions", pattern = "\\.R$", full.names = TRUE)) {
  source(file)
}

seqera_platform_logs <- createSeqeraPlatformRunCollectionFromSamplesheet(args$log_csv)

merged_logs <- getWorkflowData(seqera_platform_logs, "run_logs")
colnames(merged_logs) <- remove_prefixes(colnames(merged_logs))

merged_logs <- merged_logs %>%
  mutate(
    pipeline = clean_scalar_chr(first_present(., c("repository", "pipeline"))),
    cost = suppressWarnings(as.numeric(first_present(., "cost", NA_real_))),
    cpuTime = suppressWarnings(as.numeric(first_present(., "cpuTime", NA_real_))),
    duration = suppressWarnings(as.numeric(first_present(., "duration", NA_real_))),
    readBytes = suppressWarnings(as.numeric(first_present(., "readBytes", NA_real_))),
    writeBytes = suppressWarnings(as.numeric(first_present(., "writeBytes", NA_real_))),
    cpuEfficiency = suppressWarnings(as.numeric(first_present(., "cpuEfficiency", NA_real_))),
    memoryEfficiency = suppressWarnings(as.numeric(first_present(., "memoryEfficiency", NA_real_))),
    succeeded = coalesce(
      suppressWarnings(as.numeric(first_present(., "succeeded", NA_real_))),
      suppressWarnings(as.numeric(first_present(., "stats.succeedCount", NA_real_))),
      suppressWarnings(as.numeric(first_present(., "succeedCount", NA_real_)))
    ),
    failed = coalesce(
      suppressWarnings(as.numeric(first_present(., "failed", NA_real_))),
      suppressWarnings(as.numeric(first_present(., "stats.failedCount", NA_real_))),
      suppressWarnings(as.numeric(first_present(., "failedCount", NA_real_)))
    ),
    cached = coalesce(
      suppressWarnings(as.numeric(first_present(., "cached", NA_real_))),
      suppressWarnings(as.numeric(first_present(., "stats.cachedCount", NA_real_))),
      suppressWarnings(as.numeric(first_present(., "cachedCount", NA_real_))),
      0
    )
  ) %>%
  mutate(
    cost = round(cost, 2),
    cpuTime = round(cpuTime / 1000 / 3600, 1),
    readBytes = round(readBytes / (1024^3), 2),
    writeBytes = round(writeBytes / (1024^3), 2),
    cpuEfficiency = round(cpuEfficiency, 2),
    memoryEfficiency = round(memoryEfficiency, 2)
  )

run_id_pipeline <- merged_logs %>% select(run_id, pipeline, group)

task_data <- getWorkflowData(seqera_platform_logs, "workflow_tasks") %>%
  left_join(run_id_pipeline, by = "run_id") %>%
  mutate(
    submit = as.POSIXct(submit, format = "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC"),
    start = as.POSIXct(start, format = "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC"),
    complete = as.POSIXct(complete, format = "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC"),
    runtime_seconds = as.numeric(difftime(complete, start, units = "secs")),
    runtime_mins = as.numeric(difftime(complete, start, units = "mins")),
    waittime_mins = as.numeric(difftime(start, submit, units = "mins")),
    realtime_mins = as.numeric(realtime) / 1000 / 60,
    duration_mins = as.numeric(duration) / 1000 / 60,
    staging_time_mins = pmax(runtime_mins - realtime_mins, 0),
    process_short = str_extract(process, "[^:]+$"),
    requested_memory_gib_raw = memory / (1024^3),
    rss_gib_raw = rss / (1024^3),
    memory = round(requested_memory_gib_raw, 2),
    rss = round(rss_gib_raw, 2)
  ) %>%
  mutate(
    waittime = sprintf("%02d:%02d:%02d", floor(waittime_mins / 60), floor(waittime_mins %% 60), round((waittime_mins %% 1) * 60)),
    staging_time = sprintf("%02d:%02d:%02d", floor(staging_time_mins / 60), floor(staging_time_mins %% 60), round((staging_time_mins %% 1) * 60)),
    real_time = sprintf("%02d:%02d:%02d", floor(realtime_mins / 60), floor(realtime_mins %% 60), round((realtime_mins %% 1) * 60))
  )

task_group_lookup <- merged_logs %>% select(run_id, group) %>% distinct()
if (!"group" %in% names(task_data)) {
  task_data <- task_data %>%
    left_join(task_group_lookup, by = "run_id") %>%
    mutate(group = clean_scalar_chr(coalesce(as.character(group), "")))
} else {
  task_data <- task_data %>%
    left_join(task_group_lookup, by = "run_id", suffix = c("", "_run")) %>%
    mutate(group = clean_scalar_chr(coalesce(na_if(as.character(group), ""), as.character(group_run), ""))) %>%
    select(-any_of("group_run"))
}

if (args$remove_failed_tasks) {
  task_data <- task_data %>% filter(status == "COMPLETED")
}

task_run_metrics <- compute_task_run_metrics(task_data)
merged_logs <- merged_logs %>%
  left_join(task_run_metrics, by = c("run_id", "pipeline")) %>%
  mutate(
    cpuTime = coalesce(round(requestedCpuH, 1), cpuTime),
    cpuEfficiency = coalesce(round(cpuEfficiency_calc, 2), cpuEfficiency),
    memoryEfficiency = coalesce(round(memoryEfficiency_calc, 2), memoryEfficiency),
    task_runtime_ms = coalesce(task_runtime_ms, duration)
  ) %>%
  select(-cpuEfficiency_calc, -memoryEfficiency_calc)

machine_data <- getWorkflowData(seqera_platform_logs, "machine_data")
if (nrow(machine_data) > 0) {
  machine_run_metrics <- summarise_machine_metrics(machine_data, run_id_pipeline, task_run_metrics)
  merged_logs <- merged_logs %>% left_join(machine_run_metrics, by = c("run_id", "pipeline"))
}

cost_table <- build_cost_table(
  task_data = task_data,
  merged_logs = merged_logs,
  aws_cost = args$aws_cost,
  remove_failed_tasks = args$remove_failed_tasks
)

if (!"used_cost" %in% names(cost_table)) {
  cost_table$used_cost <- NA_real_
}
if (!"unused_cost" %in% names(cost_table)) {
  cost_table$unused_cost <- NA_real_
}

if (!is.null(args$aws_cost) && !is.na(args$aws_cost) && args$aws_cost != "") {
  cost_lookup <- cost_table %>%
    rename(
      hash_clean = hash,
      cost_report = cost,
      used_cost_report = used_cost,
      unused_cost_report = unused_cost
    )

  task_data_aug <- task_data %>%
    mutate(hash_clean = gsub("/", "", hash)) %>%
    left_join(cost_lookup, by = c("run_id", "pipeline", "group", "process", "hash_clean")) %>%
    mutate(
      cost = coalesce(cost_report, suppressWarnings(as.numeric(cost))),
      used_cost = used_cost_report,
      unused_cost = unused_cost_report
    )
} else {
  task_data_aug <- task_data %>%
    mutate(
      hash_clean = gsub("/", "", hash),
      cost = suppressWarnings(as.numeric(cost)),
      used_cost = NA_real_,
      unused_cost = NA_real_
    )
}

has_used_cost <- "used_cost" %in% names(task_data_aug)
has_unused_cost <- "unused_cost" %in% names(task_data_aug)

run_costs <- task_data_aug %>%
  group_by(run_id, group) %>%
  summarise(
    cost = if (all(is.na(cost))) NA_real_ else round(sum(cost, na.rm = TRUE), 2),
    used_cost = if (has_used_cost && !all(is.na(used_cost))) round(sum(used_cost, na.rm = TRUE), 2) else NA_real_,
    unused_cost = if (has_unused_cost && !all(is.na(unused_cost))) round(sum(unused_cost, na.rm = TRUE), 2) else NA_real_,
    .groups = "drop"
  )

workspace_values <- clean_scalar_chr(first_present(merged_logs, c("workspaceFullName", "workspaceName", "workspaceId"), ""))
platform_urls <- build_workspace_run_url(
  run_id = clean_scalar_chr(merged_logs$run_id),
  group = clean_scalar_chr(merged_logs$group),
  existing_url = first_present(merged_logs, c("runUrl"), "")
)

benchmark_overview <- merged_logs %>%
  transmute(
    pipeline = clean_scalar_chr(pipeline),
    group = clean_scalar_chr(group),
    run_id = clean_scalar_chr(run_id),
    workspace = workspace_values,
    platform_url = platform_urls
  )

run_strategy <- merged_logs %>%
  distinct(run_id, pipeline, group)
run_strategy <- bind_cols(run_strategy, detect_scheduler_profile(run_strategy$group))

run_summary <- merged_logs %>%
  left_join(run_strategy, by = c("run_id", "pipeline", "group")) %>%
  transmute(
    pipeline = clean_scalar_chr(pipeline),
    group = clean_scalar_chr(group),
    run_id = clean_scalar_chr(run_id),
    username = clean_scalar_chr(first_present(., c("userName", "username"), "")),
    Version = clean_scalar_chr(first_present(., c("workflow_revision", "revision", "Version"), "")),
    Nextflow_version = clean_scalar_chr(first_present(., c("nextflow.version", "Nextflow_version"), "")),
    platform_version = clean_scalar_chr(first_present(., c("platform_version", "version"), "")),
    succeedCount = suppressWarnings(as.numeric(first_present(., c("stats.succeedCount", "succeedCount", "succeeded"), 0))),
    failedCount = suppressWarnings(as.numeric(first_present(., c("stats.failedCount", "failedCount", "failed"), 0))),
    cachedCount = suppressWarnings(as.numeric(first_present(., c("stats.cachedCount", "cachedCount", "cached"), 0))),
    executor = clean_scalar_chr(first_present(., c("executors", "executor"), "")),
    region = clean_scalar_chr(first_present(., c("computeEnv.config.region", "region"), "")),
    fusion_enabled = as.logical(first_present(., c("computeEnv.config.fusion2Enabled", "fusion_enabled"), FALSE)),
    wave_enabled = as.logical(first_present(., c("computeEnv.config.waveEnabled", "wave_enabled"), FALSE)),
    container_engine = clean_scalar_chr(first_present(., c("containerEngine", "container_engine"), "")),
    scheduler_mode = clean_scalar_chr(first_present(., c("scheduler_mode", "scheduler_mode.x", "scheduler_mode.y"), "")),
    task_rightsizing = clean_scalar_chr(first_present(., c("rightsizing_mode", "rightsizing_mode.x", "rightsizing_mode.y"), "")),
    packing = dplyr::if_else(as.logical(first_present(., c("packing_enabled", "packing_enabled.x", "packing_enabled.y"), FALSE)), "Yes", "No"),
    vm_provisioning = clean_scalar_chr(first_present(., c("provisioning_policy", "provisioning_policy.x", "provisioning_policy.y"), ""))
  )

run_metrics <- merged_logs %>%
  left_join(run_strategy, by = c("run_id", "pipeline", "group")) %>%
  left_join(run_costs, by = c("run_id", "group")) %>%
  transmute(
    pipeline = clean_scalar_chr(pipeline),
    group = clean_scalar_chr(group),
    run_id = clean_scalar_chr(run_id),
    scheduler_mode = clean_scalar_chr(first_present(., c("scheduler_mode", "scheduler_mode.x", "scheduler_mode.y"), "")),
    task_rightsizing = clean_scalar_chr(first_present(., c("rightsizing_mode", "rightsizing_mode.x", "rightsizing_mode.y"), "")),
    packing = dplyr::if_else(as.logical(first_present(., c("packing_enabled", "packing_enabled.x", "packing_enabled.y"), FALSE)), "Yes", "No"),
    vm_provisioning = clean_scalar_chr(first_present(., c("provisioning_policy", "provisioning_policy.x", "provisioning_policy.y"), "")),
    duration = suppressWarnings(as.numeric(duration)),
    cpuTime = suppressWarnings(as.numeric(cpuTime)),
    task_runtime_ms = suppressWarnings(as.numeric(task_runtime_ms)),
    pipeline_runtime = suppressWarnings(as.numeric(task_runtime_ms)),
    cpuEfficiency = suppressWarnings(as.numeric(cpuEfficiency)),
    memoryEfficiency = suppressWarnings(as.numeric(memoryEfficiency)),
    schedAllocCpuEfficiency = suppressWarnings(as.numeric(schedAllocCpuEfficiency)),
    schedAllocMemEfficiency = suppressWarnings(as.numeric(schedAllocMemEfficiency)),
    realVmCpuEfficiency = suppressWarnings(as.numeric(realVmCpuEfficiency)),
    realVmMemEfficiency = suppressWarnings(as.numeric(realVmMemEfficiency)),
    nMachines = suppressWarnings(as.numeric(nMachines)),
    vmCpuH = suppressWarnings(as.numeric(vmCpuH)),
    vmMemGibH = suppressWarnings(as.numeric(vmMemGibH)),
    realCpuH = suppressWarnings(as.numeric(first_present(., c("realCpuH", "realCpuH.x", "realCpuH.y"), NA_real_))),
    realMemGibH = suppressWarnings(as.numeric(first_present(., c("realMemGibH", "realMemGibH.x", "realMemGibH.y"), NA_real_))),
    requestedCpuH = suppressWarnings(as.numeric(first_present(., c("requestedCpuH", "requestedCpuH.x", "requestedCpuH.y"), NA_real_))),
    requestedMemGibH = suppressWarnings(as.numeric(first_present(., c("requestedMemGibH", "requestedMemGibH.x", "requestedMemGibH.y"), NA_real_))),
    schedulerBookedCpuH = suppressWarnings(as.numeric(schedulerBookedCpuH)),
    schedulerBookedMemGibH = suppressWarnings(as.numeric(schedulerBookedMemGibH)),
    schedulerRightsizedCpuH = suppressWarnings(as.numeric(schedulerRightsizedCpuH)),
    schedulerRightsizedMemGibH = suppressWarnings(as.numeric(schedulerRightsizedMemGibH)),
    schedulerOverbookCpuH = suppressWarnings(as.numeric(schedulerOverbookCpuH)),
    schedulerOverbookMemGibH = suppressWarnings(as.numeric(schedulerOverbookMemGibH)),
    vmPackingSlackCpuH = suppressWarnings(as.numeric(vmPackingSlackCpuH)),
    vmPackingSlackMemGibH = suppressWarnings(as.numeric(vmPackingSlackMemGibH)),
    readBytes = suppressWarnings(as.numeric(readBytes)),
    writeBytes = suppressWarnings(as.numeric(writeBytes)),
    cost = suppressWarnings(as.numeric(first_present(., c("cost", "cost.x", "cost.y"), NA_real_))),
    used_cost = suppressWarnings(as.numeric(first_present(., c("used_cost", "used_cost.x", "used_cost.y"), NA_real_))),
    unused_cost = suppressWarnings(as.numeric(first_present(., c("unused_cost", "unused_cost.x", "unused_cost.y"), NA_real_)))
  )

process_stats <- task_data_aug %>%
  group_by(group, process_name = process, process_short) %>%
  summarise(
    n_tasks = n(),
    avg_staging_min = mean(staging_time_mins, na.rm = TRUE),
    sd_staging_min = safe_sd(staging_time_mins),
    avg_realtime_min = mean(realtime_mins, na.rm = TRUE),
    sd_realtime_min = safe_sd(realtime_mins),
    avg_runtime_min = mean(runtime_mins, na.rm = TRUE),
    sd_runtime_min = safe_sd(runtime_mins),
    avg_cost = if (all(is.na(cost))) NA_real_ else mean(cost, na.rm = TRUE),
    sd_cost = if (all(is.na(cost))) NA_real_ else safe_sd(cost),
    total_cost = if (all(is.na(cost))) NA_real_ else sum(cost, na.rm = TRUE),
    .groups = "drop"
  )

task_instance_usage <- task_data_aug %>%
  mutate(
    machine_type = case_when(
      !is.na(machineType) & machineType != "" ~ machineType,
      executor == "local" ~ "local",
      TRUE ~ "HPC"
    )
  ) %>%
  count(group, machine_type, name = "count")

task_scatter <- task_data_aug %>%
  transmute(
    run_id = clean_scalar_chr(run_id),
    group = clean_scalar_chr(group),
    process_short = clean_scalar_chr(process_short),
    name = clean_scalar_chr(name),
    realtime_min = suppressWarnings(as.numeric(realtime_mins)),
    staging_min = suppressWarnings(as.numeric(staging_time_mins)),
    cost = suppressWarnings(as.numeric(cost)),
    cpus = suppressWarnings(as.numeric(cpus)),
    memory_gb = suppressWarnings(as.numeric(requested_memory_gib_raw))
  )

task_table <- task_data_aug %>%
  transmute(
    Group = clean_scalar_chr(group),
    `Run ID` = clean_scalar_chr(run_id),
    Taskhash = clean_scalar_chr(hash_clean),
    `Task name short` = clean_scalar_chr(process_short),
    Executor = clean_scalar_chr(executor),
    Cloudzone = clean_scalar_chr(cloudZone),
    `Instance type` = clean_scalar_chr(machineType),
    Realtime_min = suppressWarnings(as.numeric(realtime_mins)),
    Realtime_ms = suppressWarnings(as.numeric(realtime)),
    Duration_ms = suppressWarnings(as.numeric(duration)),
    Cost = suppressWarnings(as.numeric(cost)),
    RequestedCPU = suppressWarnings(as.numeric(cpus)),
    RequestedMemory_GiB = suppressWarnings(as.numeric(memory)),
    ObservedCPU_pct = suppressWarnings(as.numeric(pcpu)),
    ObservedMemory_pct = suppressWarnings(as.numeric(pmem)),
    PeakRSS_GiB = suppressWarnings(as.numeric(rss)),
    Readbytes = suppressWarnings(as.numeric(readBytes)),
    Writebytes = suppressWarnings(as.numeric(writeBytes)),
    VolCtxt = suppressWarnings(as.numeric(volCtxt)),
    InvCtxt = suppressWarnings(as.numeric(invCtxt)),
    `Task name` = clean_scalar_chr(name),
    Status = clean_scalar_chr(status)
  )

report_data <- list(
  benchmark_overview = benchmark_overview,
  run_summary = run_summary,
  run_metrics = run_metrics,
  run_costs = run_costs,
  process_stats = process_stats,
  task_instance_usage = task_instance_usage,
  task_table = task_table,
  task_scatter = task_scatter,
  cost_overview = NULL
)

report_json <- toJSON(
  report_data,
  dataframe = "rows",
  auto_unbox = TRUE,
  na = "null",
  null = "null"
)

template <- readChar("benchmark_report_template.html", file.info("benchmark_report_template.html")$size, useBytes = TRUE)
template <- gsub("__PUBLISHED_AT__", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), template, fixed = TRUE)
template <- gsub("__FAILED_TASK_EXCLUDED__", if (args$remove_failed_tasks) "Yes" else "No", template, fixed = TRUE)
template <- gsub("__REPORT_DATA__", report_json, template, fixed = TRUE)

writeLines(template, con = args$output, useBytes = TRUE)
