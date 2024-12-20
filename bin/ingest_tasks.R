#### Task logs
## Process logs containing task level information
task_data <- seqera_platform_logs@workflow_tasks

## Add pipeline name to task_data
run_id_pipeline <- merged_logs %>% select(run_id,pipeline)
task_data <- left_join(task_data,run_id_pipeline,by = "run_id")

task_data <- task_data %>%
    mutate(submit = as.POSIXct(submit, format = "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC"),
           start = as.POSIXct(start, format = "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC"),
           complete = as.POSIXct(complete, format = "%Y-%m-%dT%H:%M:%OSZ", tz = "UTC")
           ) %>%
  mutate(runtime_seconds = as.numeric(difftime(as.POSIXct(complete), as.POSIXct(start), units = "secs")),
         runtime_mins = as.numeric(difftime(as.POSIXct(complete), as.POSIXct(start), units = "mins")),
         runtime_hours = as.numeric(difftime(as.POSIXct(complete), as.POSIXct(start), units = "hours")),
         waittime_mins = as.numeric(difftime(as.POSIXct(start), as.POSIXct(submit), units = "mins")),
         realtime_mins = (as.numeric(realtime) / 1000 / 60 ),
         duration_mins = (as.numeric(duration) / 1000 / 60 ),
         staging_time_mins = runtime_mins - realtime_mins,
         staging_time_mins = if_else(staging_time_mins < 0, 0, staging_time_mins) ## Sometimes staging time calculation can result in negative staging time, instead set it to 0
         ) %>%
  mutate(process_short = paste(str_extract(process, "[^:]+$"),sep=" - "),
        # Check if name_short has : in the name, if not, keep as is, if it does, do name_short = paste(str_extract(process, "[^:]+$")," (",tag,")",sep="")
        name_short = ifelse(grepl(":",process),paste(str_extract(process, "[^:]+$")," (",tag,")",sep=""),process)
        ) %>%
  mutate("memory" = round(memory / (1024*1024*1024),2),
          "rss" = round(rss / (1024*1024*1024),2),
          runtime = sprintf("%02d:%02d:%02d", floor(runtime_mins / 60), floor(runtime_mins %% 60), round((runtime_mins %% 1) * 60))
         ) %>%
  mutate(waittime = sprintf("%02d:%02d:%02d", floor(waittime_mins / 60), floor(waittime_mins %% 60), round((waittime_mins %% 1) * 60)),
         staging_time = sprintf("%02d:%02d:%02d", floor(staging_time_mins / 60), floor(staging_time_mins %% 60), round((staging_time_mins %% 1) * 60)),
         real_time = sprintf("%02d:%02d:%02d", floor(realtime_mins / 60), floor(realtime_mins %% 60), round((realtime_mins %% 1) * 60))
         )

## TODO: Establish task group ordering via group inside functions in the future
# # Also for task level data, ensure that Seqera label is first / baseline if present
# if("Seqera" %in% unique(seqera_platform_logs@group)){ ## If doing quicklaunch
#     other_groups <- unique(seqera_platform_logs@group)[!unique(seqera_platform_logs@group) %in% "Seqera"]
#     task_data$group <- factor(task_data$group,levels = c("Seqera",other_groups))
# }else{
#   ## Otherwise, take the order of unique labels as provided in the samplesheet input
#   task_data$group <- factor(task_data$group, levels = unique(log_files$group))
# }

## If user wants to filter out failed tasks for calculations, remove them
if(params$remove_failed_tasks != "NA"){
  task_data <- task_data %>%
    subset(status == "COMPLETED")
}

# Some sanity checks
first_task <- task_data %>%
  # Get the row with the earlierst submit field per run_id in task_data
  group_by(run_id) %>%
  filter(submit == min(submit)) %>%
  ungroup()

#####
## Add pipeline runtime to merged_logs. Pipeline run time is defined as staging + real time from all tasks combined
pipeline_total_runtime <- task_data %>%
  group_by(run_id,pipeline) %>%
  summarise(pipeline_runtime = sum(runtime_mins) * 1000 * 60 ) %>% ## Converting minutes back to milliseconds here to be able to reuse functions
  ungroup()

merged_logs <- left_join(merged_logs,pipeline_total_runtime,by=c("run_id","pipeline"))

##### Add total workdir size to merged_logs if available
# Check if workdirsizes are provided in the task log
# Check if workdirSize is in colnames of task_data
if("workdirSize" %in% colnames(task_data)){
  aws_s3_price_perGB <- 0.023
  fsx_price_perGB    <- 0.154

  workdirSizes <- task_data %>%
    # Check if fsx is in the string in the column workdir and create a new column storage_type
    mutate(storage_type = if_else(str_detect(workdir, "fsx"),"FSx","S3")) %>%
    group_by(run_id,pipeline,storage_type) %>%
    summarise(pipeline_workdirSize = sum(workdirSize)) %>%
    #Convert pipeline_workdirSize from bytes to GB
    mutate(pipeline_workdirSize_GB = pipeline_workdirSize / (1024*1024*1024)) %>%
    mutate(pipeline_workdirSize_price = if_else(storage_type == "FSx"
                                                  ,pipeline_workdirSize_GB * fsx_price_perGB,
                                                  pipeline_workdirSize_GB * aws_s3_price_perGB)) %>%
    ungroup()

merged_logs <- left_join(merged_logs,workdirSizes,by=c("run_id","pipeline"))
}
```


```{r generate-cost-table}
#| echo: false
#| include: false
#| results: hide

## This code block will read in the aws data export if provided and the estimated cost from Seqera Platform
## Both cost tables will be formatted the same way, so that the accurate cost report can simple be used in place of the estimated cost report

accurate_task_costs <- data.frame()
## Check whether accurate cost reports are available
if(params$aws_cost != "NA") {
  # Check whether params$aws_cost is a txt file or a parquet file
  if(grepl(".txt",params$aws_cost)){
    aws_reports_list <- fread(params$aws_cost, header = FALSE)
    # Read and combine all parquet files from the list
    aws_cost_table <- aws_reports_list$V1 %>%
      lapply(read_parquet) %>%
      bind_rows()
  }else{
    aws_cost_table <- read_parquet(params$aws_cost)
  }

  ## Select only relevant columns
  aws_cur_cols <- c("identity_line_item_id",
                     "resource_tags_user_unique_run_id",
                     "line_item_usage_type",
                     "split_line_item_split_cost",
                     "split_line_item_unused_cost",
                     "line_item_blended_cost",
                     "resource_tags_user_pipeline_process",
                     "resource_tags_user_task_hash")

  aws_cost_table <- aws_cost_table %>%
    subset(resource_tags_user_unique_run_id %in% merged_logs$run_id)

  accurate_task_costs <- aws_cost_table %>%
    select(all_of(aws_cur_cols)) %>%
    mutate("cost"     = split_line_item_split_cost + split_line_item_unused_cost,
           "used_cost"= split_line_item_split_cost,
           "unused_cost" = split_line_item_unused_cost) %>%
    mutate("run_id"    = resource_tags_user_unique_run_id,
           "process"  = resource_tags_user_pipeline_process,
           "hash" = resource_tags_user_task_hash)
  # Take only the first 8 characters of the hash
  accurate_task_costs$hash <- substr(accurate_task_costs$hash,1,8)

  ## Add group to accurate_task_costs
  accurate_task_costs <- accurate_task_costs %>%
    left_join(merged_logs %>% select(run_id,group,pipeline), by = "run_id")

  ## Sum up costs for cpu and memory
  accurate_task_costs <- accurate_task_costs %>%
    group_by(run_id,pipeline,Group,process,hash) %>%
    summarise(cost = sum(cost),
              used_cost = sum(used_cost),
              unused_cost = sum(unused_cost)) %>%
    ungroup()
}

## If we don't have a accurate cost report, we will use the estimated cost from platform for all cost reporting
if(length(unique(merged_logs$executors)) > 1){ ## If we are comparing runs from different executors (i.e. slurm vs )
  estim_task_costs <- task_data %>%
    select(run_id,pipeline,group,process,cost,hash)
  estim_task_costs$hash <- gsub("/","",estim_task_costs$hash)
}else if(length(unique(merged_logs$executors)) == 1){ ## We are comparing runs from the same executor
  if(unique(merged_logs$executors) == "azure-batch"){
      estim_task_costs <- task_data %>%
        select(run_id,pipeline,group,process,hash)
      estim_task_costs$hash <- gsub("/","",estim_task_costs$hash)
  }else if (unique(merged_logs$executors) == "google-batch"){
    estim_task_costs <- task_data %>%
      select(run_id,pipeline,group,process,hash)
    estim_task_costs$hash <- gsub("/","",estim_task_costs$hash)
  }else{
    estim_task_costs <- task_data %>%
      select(run_id,pipeline,group,process,cost,hash)
  estim_task_costs$hash <- gsub("/","",estim_task_costs$hash)
  }
}

## Check which scenario the user wants to view
## 1) Use estimated costs
if(grepl("cost",profile) & nrow(accurate_task_costs) == 0){
  cost_table <- estim_task_costs
}else if(grepl("cost",profile) & nrow(accurate_task_costs) > 1){
## 2) Use accurate costs
  cost_table <- accurate_task_costs
}

## Filter for completed task if param is set
if(grepl("cost",profile) & params$remove_failed_tasks != "NA"){
  task_data_sub_cost <- task_data %>% select("run_id","hash","status")
  task_data_sub_cost$hash <- gsub("/","",task_data_sub_cost$hash)
  cost_table <- left_join(cost_table,task_data_sub_cost,by=c("run_id","hash"))
  cost_table <- cost_table %>%
    subset(status == "COMPLETED")
}
```
