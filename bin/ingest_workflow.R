#!/usr/bin/env Rscript

library(optparse)
library(tidyverse)
library(jsonlite)

# Parse command line arguments
option_list <- list(
  make_option(c("--workflow"), type="character", help="Path to workflow.json"),
  make_option(c("--workflow_load"), type="character", help="Path to workflow-load.json"),
  make_option(c("--workflow_launch"), type="character", help="Path to workflow-launch.json"),
  make_option(c("--service_info"), type="character", help="Path to service-info.json"),
  make_option(c("--output"), type="character", help="Output prefix for CSV files")
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

# Read JSON files
workflow_data <- safe_read_json(opt$workflow)
workflow_load <- safe_read_json(opt$workflow_load)
workflow_launch <- safe_read_json(opt$workflow_launch)
service_info <- safe_read_json(opt$service_info)

# Process workflow data (required)
if (length(workflow_data) == 0) {
  stop("workflow.json is empty or invalid")
}

workflow_df <- data.frame(
  run_id = workflow_data$id,
  repository = workflow_data$repository,
  duration = workflow_data$duration,
  cost = safe_extract(workflow_data, "cost"),
  cpuTime = safe_extract(workflow_data, "cpuTime"),
  readBytes = safe_extract(workflow_data, "readBytes"),
  writeBytes = safe_extract(workflow_data, "writeBytes"),
  cpuEfficiency = safe_extract(workflow_data, "cpuEfficiency"),
  memoryEfficiency = safe_extract(workflow_data, "memoryEfficiency"),
  succeeded = workflow_data$stats$succeedCount,
  failed = workflow_data$stats$failedCount,
  cached = workflow_data$stats$cachedCount,
  stringsAsFactors = FALSE
)

# Process workflow load data (optional)
workflow_load_df <- if (length(workflow_load) > 0) {
  data.frame(
    run_id = safe_extract(workflow_load, "runId", workflow_df$run_id),
    executor = safe_extract(workflow_load, "executor", NA),
    container = safe_extract(workflow_load, "container", NA),
    stringsAsFactors = FALSE
  )
} else {
  data.frame(
    run_id = workflow_df$run_id,
    executor = NA,
    container = NA,
    stringsAsFactors = FALSE
  )
}

# Process workflow launch data (optional)
workflow_launch_df <- if (length(workflow_launch) > 0) {
  data.frame(
    run_id = safe_extract(workflow_launch, "runId", workflow_df$run_id),
    launch_time = safe_extract(workflow_launch, "timestamp", NA),
    stringsAsFactors = FALSE
  )
} else {
  data.frame(
    run_id = workflow_df$run_id,
    launch_time = NA,
    stringsAsFactors = FALSE
  )
}

# Process service info data (optional)
service_info_df <- if (length(service_info) > 0) {
  data.frame(
    run_id = workflow_df$run_id,
    platform_version = safe_extract(service_info, "version", NA),
    seqera_cloud = safe_extract(service_info, "seqeraCloud", NA),
    stringsAsFactors = FALSE
  )
} else {
  data.frame(
    run_id = workflow_df$run_id,
    platform_version = NA,
    seqera_cloud = NA,
    stringsAsFactors = FALSE
  )
}

# Merge all dataframes
merged_logs <- workflow_df %>%
  left_join(workflow_load_df, by = "run_id") %>%
  left_join(workflow_launch_df, by = "run_id") %>%
  left_join(service_info_df, by = "run_id")

# Convert and round numeric columns
merged_logs <- merged_logs %>%
  mutate(across(c(cost, cpuTime, readBytes, writeBytes, cpuEfficiency, memoryEfficiency, succeeded, failed, cached),
                ~as.numeric(as.character(.)))) %>%
  mutate(
    cost = round(cost, 2),
    cpuTime = round(cpuTime / 60 / 60 / 1000, 1),
    readBytes = round(readBytes / (1024*1024*1024), 2),
    writeBytes = round(writeBytes / (1024*1024*1024), 2),
    cpuEfficiency = round(cpuEfficiency, 2),
    memoryEfficiency = round(memoryEfficiency, 2),
    total_tasks = succeeded + failed + cached
  )

# Extract pipeline name from repository URL
merged_logs$pipeline <- str_extract(merged_logs$repository, "[^/]+$")

# Write output
write.csv(merged_logs, file = opt$output, row.names = FALSE, quote = TRUE)
