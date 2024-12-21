#!/usr/bin/env Rscript

# Load required libraries
library(optparse)
library(tidyverse)
library(jsonlite)

# Define command line arguments
option_list <- list(
    make_option(c("--workflow"), type="character", help="Path to workflow.json"),
    make_option(c("--workflow_load"), type="character", help="Path to workflow-load.json"),
    make_option(c("--workflow_launch"), type="character", help="Path to workflow-launch.json"),
    make_option(c("--service_info"), type="character", help="Path to service-info.json"),
    make_option(c("--output"), type="character", help="Output CSV file path")
)

# Parse command line arguments
opt <- parse_args(OptionParser(option_list=option_list))

# Read JSON files
workflow_data <- fromJSON(opt$workflow)
workflow_load <- fromJSON(opt$workflow_load)
workflow_launch <- fromJSON(opt$workflow_launch)
service_info <- fromJSON(opt$service_info)

# Convert to data frames and ensure consistent run_id column
workflow_df <- as.data.frame(workflow_data)
workflow_load_df <- as.data.frame(workflow_load)
workflow_launch_df <- as.data.frame(workflow_launch)
service_info_df <- as.data.frame(service_info)

# Merge information across logs containing run level information
merged_logs <- full_join(workflow_df, workflow_load_df, by = "run_id")
merged_logs <- full_join(merged_logs, workflow_launch_df, by="run_id")
merged_logs <- full_join(merged_logs, service_info_df, by="run_id")

## Add pipeline name from Repository URL, take the element after the last /
merged_logs$pipeline <- str_extract(merged_logs$repository, "[^/]+$")
if("nf-stresstest" %in% unique(merged_logs$pipeline)){
    merged_logs$pipeline <- as.character(merged_logs$run_name)
}

# Convert multiple columns to numeric
merged_logs <- merged_logs %>%
    mutate("cost" = as.numeric(cost),
           "cpuTime" = as.numeric(cpuTime),
           "readBytes" = as.numeric(readBytes),
           "writeBytes" = as.numeric(writeBytes),
           "cpuEfficiency" = as.numeric(cpuEfficiency),
           "memoryEfficiency" = as.numeric(memoryEfficiency),
           "succeeded" = as.numeric(succeeded),
           "failed" = as.numeric(failed),
           "cached" = as.numeric(cached)
    )

merged_logs <- merged_logs %>%
    mutate("cost" = round(cost,2),
           "cpuTime" = round(cpuTime / 60 / 60 / 1000,1),
           "readBytes" = round(readBytes / (1024*1024*1024),2),
           "writeBytes" = round(writeBytes / (1024*1024*1024),2),
           "cpuEfficiency" = round(cpuEfficiency,2),
           "memoryEfficiency" = round(memoryEfficiency,2),
           "total_tasks" = succeeded + failed + cached
    ) %>%
    arrange(pipeline)

# Write output
write.csv(merged_logs, opt$output, row.names = FALSE)
```

