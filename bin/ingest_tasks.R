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

# Function to safely extract JSON fields
safe_extract <- function(json, element, default = NA) {
  if (!is.null(json[[element]])) {
    return(json[[element]])
  } else {
    return(default)
  }
}

# Function to safely read JSON files
safe_read_json <- function(file_path) {
  tryCatch({
    fromJSON(file_path)
  }, error = function(e) {
    warning(sprintf("Could not read %s: %s", file_path, e$message))
    list()
  })
}

# Read tasks JSON file
tasks_data <- safe_read_json(opt$tasks)

if (length(tasks_data) == 0) {
  stop("tasks.json is empty or invalid")
}

# Process tasks data
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

# Convert numeric columns and calculate derived metrics
tasks_df <- tasks_df %>%
  mutate(
    # Convert memory metrics to GB
    memory = round(memory / (1024*1024*1024), 2),
    rss = round(rss / (1024*1024*1024), 2),
    vmem = round(vmem / (1024*1024*1024), 2),
    peak_rss = round(peak_rss / (1024*1024*1024), 2),
    peak_vmem = round(peak_vmem / (1024*1024*1024), 2),

    # Convert byte metrics to GB
    read_bytes = round(read_bytes / (1024*1024*1024), 2),
    write_bytes = round(write_bytes / (1024*1024*1024), 2),
    rchar = round(rchar / (1024*1024*1024), 2),
    wchar = round(wchar / (1024*1024*1024), 2),

    # Convert time metrics to minutes
    duration = round(duration / 1000 / 60, 2),
    realtime = round(realtime / 60, 2),
    time = round(time / 1000 / 60, 2),

    # Round other numeric metrics
    cost = round(cost, 4),
    pcpu = round(pcpu, 2),
    pmem = round(pmem, 2)
  )

# Convert timestamps to POSIXct
tasks_df <- tasks_df %>%
  mutate(
    submit_time = as.POSIXct(submit_time, format="%Y-%m-%dT%H:%M:%SZ", tz="UTC"),
    start_time = as.POSIXct(start_time, format="%Y-%m-%dT%H:%M:%SZ", tz="UTC"),
    complete_time = as.POSIXct(complete_time, format="%Y-%m-%dT%H:%M:%SZ", tz="UTC")
  )

# Extract pipeline name from process field
tasks_df$pipeline <- str_extract(tasks_df$process, "^[^:]+")

# Write output
write.csv(tasks_df, file = opt$output, row.names = FALSE, quote = TRUE)
```

