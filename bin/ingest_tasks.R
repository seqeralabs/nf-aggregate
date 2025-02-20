#!/usr/bin/env Rscript

library(optparse)
library(tidyverse)
library(jsonlite)

# Parse command line arguments
option_list <- list(
  make_option(c("--tasks"), type="character", help="Path to workflow-tasks.json"),
  make_option(c("--output"), type="character", help="Output path for CSV file")
)

opt <- parse_args(OptionParser(option_list=option_list))

# Function to safely extract JSON fields with debugging
safe_extract <- function(json, element, default = NA) {
  tryCatch({
    if (is.null(json) || !element %in% names(json)) {
      return(default)
    }
    value <- json[[element]]
    if (is.null(value)) {
      return(default)
    }
    return(value)
  }, error = function(e) {
    warning(sprintf("Error extracting %s: %s", element, e$message))
    return(default)
  })
}

# Function to safely read JSON files
safe_read_json <- function(file_path) {
  tryCatch({
    json_data <- fromJSON(file_path)
    # Print structure for debugging
    cat("JSON structure:\n")
    str(json_data, max.level = 2)
    return(json_data)
  }, error = function(e) {
    warning(sprintf("Could not read %s: %s", file_path, e$message))
    return(list())
  })
}

# Read tasks JSON file
tasks_data <- safe_read_json(opt$tasks)

if (length(tasks_data) == 0) {
  stop("tasks.json is empty or invalid")
}

# Process tasks data with better error handling
tasks_df <- tryCatch({
  # Check if tasks_data is already a data frame
  if (is.data.frame(tasks_data)) {
    tasks_df <- tasks_data
  } else {
    # If it's a list, process it
    tasks_df <- map_df(tasks_data, function(task) {
      data.frame(
        task_id = safe_extract(task, "taskId"),
        hash = safe_extract(task, "hash"),
        name = safe_extract(task, "name"),
        process = safe_extract(task, "process"),
        tag = safe_extract(task, "tag"),
        status = safe_extract(task, "status"),
        container = safe_extract(task, "container"),
        attempt = safe_extract(task, "attempt"),
        submit_time = safe_extract(task, "submit"),
        start_time = safe_extract(task, "start"),
        complete_time = safe_extract(task, "complete"),
        duration = safe_extract(task, "duration"),
        realtime = safe_extract(task, "realtime"),
        queue = safe_extract(task, "queue"),
        cpus = safe_extract(task, "cpus"),
        memory = safe_extract(task, "memory"),
        disk = safe_extract(task, "disk"),
        time = safe_extract(task, "time"),
        executor = safe_extract(task, "executor"),
        machine_type = safe_extract(task, "machineType"),
        cloud_zone = safe_extract(task, "cloudZone"),
        price_model = safe_extract(task, "priceModel"),
        cost = safe_extract(task, "cost"),
        exit_status = safe_extract(task, "exitStatus"),
        pcpu = safe_extract(task, "pcpu"),
        pmem = safe_extract(task, "pmem"),
        rss = safe_extract(task, "rss"),
        vmem = safe_extract(task, "vmem"),
        peak_rss = safe_extract(task, "peakRss"),
        peak_vmem = safe_extract(task, "peakVmem"),
        rchar = safe_extract(task, "rchar"),
        wchar = safe_extract(task, "wchar"),
        syscr = safe_extract(task, "syscr"),
        syscw = safe_extract(task, "syscw"),
        read_bytes = safe_extract(task, "readBytes"),
        write_bytes = safe_extract(task, "writeBytes"),
        vol_ctxt = safe_extract(task, "volCtxt"),
        inv_ctxt = safe_extract(task, "invCtxt"),
        stringsAsFactors = FALSE
      )
    })
  }
  tasks_df
}, error = function(e) {
  stop(sprintf("Error processing tasks data: %s\nJSON structure:\n%s",
               e$message, str(tasks_data)))
})

# Convert numeric columns and calculate derived metrics
tasks_df <- tasks_df %>%
  mutate(across(where(is.numeric), ~ifelse(is.na(.), ., .))) %>%
  mutate(
    # Convert memory metrics to GB (if not NA)
    memory = if_else(!is.na(memory), round(memory / (1024*1024*1024), 2), memory),
    rss = if_else(!is.na(rss), round(rss / (1024*1024*1024), 2), rss),
    vmem = if_else(!is.na(vmem), round(vmem / (1024*1024*1024), 2), vmem),
    peak_rss = if_else(!is.na(peak_rss), round(peak_rss / (1024*1024*1024), 2), peak_rss),
    peak_vmem = if_else(!is.na(peak_vmem), round(peak_vmem / (1024*1024*1024), 2), peak_vmem),

    # Convert byte metrics to GB (if not NA)
    read_bytes = if_else(!is.na(read_bytes), round(read_bytes / (1024*1024*1024), 2), read_bytes),
    write_bytes = if_else(!is.na(write_bytes), round(write_bytes / (1024*1024*1024), 2), write_bytes),
    rchar = if_else(!is.na(rchar), round(rchar / (1024*1024*1024), 2), rchar),
    wchar = if_else(!is.na(wchar), round(wchar / (1024*1024*1024), 2), wchar),

    # Convert time metrics to minutes (if not NA)
    duration = if_else(!is.na(duration), round(duration / 1000 / 60, 2), duration),
    realtime = if_else(!is.na(realtime), round(realtime / 60, 2), realtime),
    time = if_else(!is.na(time), round(time / 1000 / 60, 2), time),

    # Round other numeric metrics (if not NA)
    cost = if_else(!is.na(cost), round(cost, 4), cost),
    pcpu = if_else(!is.na(pcpu), round(pcpu, 2), pcpu),
    pmem = if_else(!is.na(pmem), round(pmem, 2), pmem)
  )

# Convert timestamps to POSIXct with error handling
tasks_df <- tasks_df %>%
  mutate(across(c(submit_time, start_time, complete_time),
                ~tryCatch(
                  as.POSIXct(., format="%Y-%m-%dT%H:%M:%SZ", tz="UTC"),
                  error = function(e) NA
                )))

# Extract pipeline name from process field if it exists
tasks_df$pipeline <- ifelse(!is.na(tasks_df$process),
                           str_extract(tasks_df$process, "^[^:]+"),
                           NA)

# Write output
write.csv(tasks_df, file = opt$output, row.names = FALSE, quote = TRUE)
```

