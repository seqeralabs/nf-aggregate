```{r read-platform-logs}
#| echo: false
#| include: false
#| results: hide

seqera_platform_logs <- createSeqeraRunCollectionFromSamplesheet(params$log_csv)
seqera_platform_logs <- addGroupToWorkflows(seqera_platform_logs)
```


```{r merge-platform-logs}
#| echo: false
#| include: false
#| results: hide

#### Merge information across logs containing run level information
merged_logs <- full_join(seqera_platform_logs@workflow, seqera_platform_logs@workflow_load, by = "run_id") ## workflow and load logs
merged_logs <- full_join(merged_logs,seqera_platform_logs@workflow_launch,by="run_id") ## launch logs
merged_logs <- full_join(merged_logs,seqera_platform_logs@service_info,by="run_id") ## service logs
merged_logs$group <- seqera_platform_logs@group

## Add pipeline name from  Repository URL, take the element after the last /
merged_logs$pipeline <- str_extract(merged_logs$repository, "[^/]+$")
if("nf-stresstest" %in% unique(merged_logs$pipeline)){
  merged_logs$pipeline <- as.character(merged_logs$run_name)
}

# Use tidy to convert multiple columns to numeric in merged_logs dataframe
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

## Set the factor order level of pipelines based on min walltime per group
pipeline_order <- merged_logs %>%
  ungroup() %>%
  group_by(pipeline) %>%
  summarise(min_walltime = min(duration)) %>%
  arrange(min_walltime) %>%
  pull(pipeline)

merged_logs$pipeline <- factor(merged_logs$pipeline,
                               levels = rev(pipeline_order))

## If Seqera is one of the group labels, make Seqera be the first group / baseline
if("Seqera" %in% unique(seqera_platform_logs@group)){ ## If doing quicklaunch
    other_groups <- unique(merged_logs$group)[!unique(merged_logs$group) %in% "Seqera"]
    merged_logs$group <- factor(merged_logs$group, levels = c("Seqera",other_groups))
}else{
  merged_logs$group <- factor(merged_logs$group,levels = unique(seqera_platform_logs@group))
}

groups_color_palette <- groups_color_palette[1:length(unique(merged_logs$group))]
names(groups_color_palette) <- unique(merged_logs$group)

## Determine how many maximum runs were done per pipeline (for example maybe one pipeline was run 3 times)
n_runs <- merged_logs %>%
  group_by(group,pipeline) %>%
  summarise(n = n())
n_runs_max <- max(n_runs$n)

## Determine how many groups there are
n_groups <- length(unique(merged_logs$group))
