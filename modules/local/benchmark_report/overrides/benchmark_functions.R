library(RColorBrewer)
library(pals)

## Color options for grouping
groups_color_palette <- c("#0DC09D","#3D95FD","#F18046","#160F26","#FA6863","#EAEBEB")
instance_palette <- alphabet2()
# Add another color palette to instance_palette to make it be able to be used with up to 50 colors
instance_palette <- c(instance_palette, alphabet())

# based on palette by Paul Tol: https://personal.sron.nl/~pault/
#groups_color_palette <- c("#4477AA", "#EE6677", "#228833", "#CCBB44","#66CCEE", "#AA3377", "#BBBBBB") 

# Define a function to convert hex colors to RGBA with alpha
hex_to_rgba <- function(hex, alpha) {
  rgb <- col2rgb(hex)
  rgba <- sprintf("rgba(%d,%d,%d,%.2f)", rgb[1], rgb[2], rgb[3], alpha)
  return(rgba)
}

## Include functions
create_link <- function(value, url_table) {
  if(length(value) > 1){
    id_unlist <- unlist(value)
    id_url_list <- list()
    for(id in id_unlist){
      url <- url_table$runUrl[url_table$run_id == id]
      id_url_list <- c(id_url_list,sprintf('<a href="%s" target="_blank">%s</a>', url, id))
    }
    # connect strings in id_url_list
    return(paste(id_url_list, collapse = " \n"))
  }else{
    if (is.na(value) || !value %in% url_table$run_id) {
      return(value)  # Return the value as is if no URL mapping is found
    }
    url <- url_table$runUrl[url_table$run_id == value]
    if (length(url) == 0 || is.na(url)) {
      return(value)  # Return the value as is if URL is missing or NA
    }
    if (length(url) == 0 || is.na(url)) {
      return(value)  # Return the value as is if URL is missing or NA
    }
    sprintf('<a href="%s" target="_blank">%s</a>', url, value)
  }
}

# Function to extract json fields safely
safe_extract <- function(json, element, default = NA) {
  if (!is.null(json[[element]])) {
    return(json[[element]])
  } else {
    return(default)
  }
}

set_ggplotly_font <- function(plotly_obj) {
  plotly_obj %>%
    layout(
      legend = list(
        font = list(size = 17),
        title = list(font = list(size = 17))
      )
    )
}

# Function to add padding to single-digit numbers
pad_labels <- function(x) {
  ifelse(nchar(x) == 1 | nchar(x) == 2, paste0(" ", x, " "), x)
}

# Function to convert hours in double format to HH:MM:SS
milliseconds_to_hms <- function(time_ms) {
  if (is.null(time_ms) || length(time_ms) == 0 || is.na(time_ms)) {
    return(NA_character_)
  }
  
  time_sec <- time_ms / 1000
  hours <- floor(time_sec / 3600)
  minutes <- floor((time_sec %% 3600) / 60)
  seconds <- round(time_sec %% 60)
  
  # Adjust minutes and hours if seconds round to 60
  if (seconds == 60) {
    seconds <- 0
    minutes <- minutes + 1
    if (minutes == 60) {
      minutes <- 0
      hours <- hours + 1
    }
  }
  
  sprintf("%02d:%02d:%02d", hours, minutes, seconds)
}


## Parse tw run dumps tar.gz files
process_platform_logs <- function(log_files){
  
  all_log_paths <- c()
  base_paths <- c()
  
  ## Process logs for each run specified in log_files
  for (i in 1:nrow(log_files)){
    file_path <- log_files[i, file_path]
    file_basepath <- gsub(".tar.gz", "", file_path)
    base_paths <- c(base_paths, file_basepath)
    if(file.exists(file_path)){
      if(!dir.exists(file_basepath)){
        if(endsWith(file_path, ".tar.gz")){
          untar(file_path, exdir = file_basepath)
        }
      }
      
      # Check for double-nested folder structure
      nested_folder <- list.files(file_basepath, full.names = TRUE)
      if(length(nested_folder) == 1 && dir.exists(nested_folder)){
        file_basepath <- nested_folder
      }
      
      log_file_names <- list.files(file_basepath)
      ## Some manual checks to make sure log files are inside file_basepath
      if(length(log_file_names) == 0){
        stop(paste("Error: The file:", file_path, "you were trying to access does not contain any files!"))
      } else {
        # Check that all json files are inside log_file_names
        required_files <- c("workflow.json", "service-info.json", "workflow-load.json", "workflow-launch.json", "workflow-tasks.json", "workflow-metadata.json")
        if(!all(required_files %in% log_file_names)){
          missing_files <- setdiff(required_files, log_file_names)
          stop(paste("Error: The file:", file_path, "you were trying to access does not contain all the necessary json log files:\n",
                     paste("- ", missing_files, collapse = "\n")))
        }
      }
      unzipped_files <- list.files(file_basepath, full.names = TRUE)
      all_log_paths <- c(all_log_paths, unzipped_files)
    } else {
      stop(paste("Error: The file:", file_path, "you were trying to access does not exist!"))
    }
  }
  
  ## Add baspaths as column to log_files for easy group lookup
  log_files$base_path <- base_paths
  log_files$workflow_logs <-  all_log_paths[grepl("workflow.json", all_log_paths)]
  log_files$service_logs <- all_log_paths[grepl("service-info.json", all_log_paths)]
  log_files$load_logs <-  all_log_paths[grepl("workflow-load.json", all_log_paths)]
  log_files$launch_logs <- all_log_paths[grepl("workflow-launch.json", all_log_paths)]
  # Check if a file named workflow-tasks.workdir_size.json is available in all_log_paths and add it to log_files if it exists
  if(length(unique(grepl("workflow-tasks.workdir_size.json", all_log_paths))) > 1) {
    log_files$task_logs <- all_log_paths[grepl("workflow-tasks.workdir_size.json", all_log_paths)]
  }else{
    log_files$task_logs <- all_log_paths[grepl("workflow-tasks.json", all_log_paths)]
  }
  meta_logs <- all_log_paths[grepl("workflow-metadata.json", all_log_paths)]
  # For all file paths in all_log_paths, check whether their base path exists in log_files$base_path. If it does, add that file path as a column to log_files, otherwise add an empty string
  log_files$meta_logs <- sapply(log_files$base_path, function(base_path){
    # Construct the expected file path from base_path
    expected_path <- paste0(base_path, "/workflow-metadata.json")
    # Check if the expected path exists in meta_logs
    if (expected_path %in% meta_logs) {
      return(expected_path)
    } else {
      return("")
    }
  })
  
  ################
  #### Workflow logs
  ## Read in the json files for each dir in unzipped files. Add the name of the dir as a column
  tw_run_dumps_workflow <- apply(log_files,1, function(row){
    workflow_log <- row["workflow_logs"]
    json_data <- jsonlite::fromJSON(workflow_log)
    start_time <- ymd_hms(json_data$start)
    complete_time <- ymd_hms(json_data$complete)
    
    wall_time <- milliseconds_to_hms(json_data$duration)
    
    # Check if the run name of json_data contains nf-stresstest
    if(grepl("nf-stresstest", json_data$runName)){
      runName <- as.character(str_extract(json_data$runName, "[A-Z]{3}\\d+"))
    }else{
      runName <- json_data$runName
    }
 
    # Extract the summary
    json_data <- data.frame(
      RunID = json_data$id,
      Group = row["group"],
      run_name = runName,
      Repository = json_data$repository,
      Version =  safe_extract(json_data, "revision"),
      Wall_time = wall_time,
      duration = json_data$duration,
      Nextflow_version = json_data$nextflow$version,
      #pipeline = json_data$manifest$name,
      succeedCount = json_data$stats$succeedCount,
      failedCount = json_data$stats$failedCount,
      username = json_data$userName,
      stringsAsFactors = FALSE
    )
  })
  
  ## Combine the data.tables into a single data.table
  tw_run_dumps_workflow_full <- rbindlist(tw_run_dumps_workflow, fill = TRUE)
  tw_run_dumps_workflow_full <- tw_run_dumps_workflow_full %>% unique()
  
  ## Add RunID from workflow.json to log_files for easy access for other logs
  log_files$RunID <- tw_run_dumps_workflow_full$RunID
  
  ################
  #### SERVICE logs
  tw_run_dumps_service <- apply(log_files,1, function(row){
    service_log <- row["service_logs"]
    json_data <- jsonlite::fromJSON(service_log)
    
    #json_data$RunID <- sapply(strsplit(service_log, "/"), function(json_data) json_data[length(json_data) - 1])
    json_data <- data.frame(
      #sample_name = json_data$runName,
      RunID = row["RunID"],
      platform_version = json_data$version,
      seqeraCloud = json_data$seqeraCloud,
      stringsAsFactors = FALSE
    )
  })
  
  tw_run_dumps_service_full <- rbindlist(tw_run_dumps_service, fill = TRUE)
  tw_run_dumps_service_full <- tw_run_dumps_service_full %>% unique()
  
  ################
  #### LOAD logs
  tw_run_dumps_load <- apply(log_files,1, function(row){
    load_log <- row["load_logs"]
    json_data <- jsonlite::fromJSON(load_log)
    json_data <- as.data.frame(json_data)
    json_data$RunID <- row["RunID"]
    # Identify columns with different values
    diff_cols <- sapply(json_data, function(col) length(unique(col)) > 1)
    
    # For columns with different values, join them into a single string
    for (col in names(json_data)[diff_cols]) {
      json_data[[col]] <- paste(unique(json_data[[col]]), collapse = ",")
    }
    
    # Convert to a single row data frame
    json_data <- json_data[1, , drop = FALSE]
    
    # Ensure RunID is included
    json_data$RunID <- row["RunID"]
    json_data

  })
  tw_run_dumps_load_full <- rbindlist(tw_run_dumps_load, fill = TRUE)
  tw_run_dumps_load_full <- tw_run_dumps_load_full %>% unique()
  
  ################
  #### LAUNCH logs
  tw_run_dumps_launch <- apply(log_files,1, function(row){
    launch_log <- row["launch_logs"]
    json_data <- jsonlite::fromJSON(launch_log)
    
    # Define expected fields
    expected_fields <- c("workDir", "preRunScript", "resume", "pullLatest", "stubRun", "configProfiles", "dateCreated", "lastUpdated", "computeEnv")
    
    # Check for missing fields
    missing_fields <- setdiff(expected_fields, names(json_data))
    if (length(missing_fields) > 0) {
      warning(paste("Missing fields in launch log for RunID", row["RunID"], ":", paste(missing_fields, collapse = ", ")))
    }
    
    # Use safe_extract for all fields
    json_data <- data.frame(
      RunID = row["RunID"],
      work_dir = safe_extract(json_data, "workDir"),
      pre_run_script = paste(safe_extract(json_data, "preRunScript", ""), collapse = ", "),
      resume = safe_extract(json_data, "resume"),
      pull_latest = safe_extract(json_data, "pullLatest"),
      stub_run = safe_extract(json_data, "stubRun"),
      config_profiles = paste(safe_extract(json_data, "configProfiles", ""), collapse = ", "),
      date_created = safe_extract(json_data, "dateCreated"),
      last_updated = safe_extract(json_data, "lastUpdated"),
      executor = safe_extract(json_data$computeEnv, "platform"),
      provisioning = ifelse(is.null(json_data$computeEnv$platform), NA,
                            switch(json_data$computeEnv$platform,
                                   "slurm-platform" = "HPC",
                                   "google-batch" = "google-batch",
                                   "azure-batch" = "azure-batch",
                                   safe_extract(json_data$computeEnv$config$forge, "type"))),
      max_cpu = ifelse(is.null(json_data$computeEnv$platform), NA,
                       switch(json_data$computeEnv$platform,
                              "slurm-platform" = "NA",
                              "google-batch" = "NA",
                              "azure-batch" = "NA",
                              safe_extract(json_data$computeEnv$config$forge, "maxCpus"))),
      gpu_enabled = ifelse(is.null(json_data$computeEnv$platform), NA,
                           switch(json_data$computeEnv$platform,
                                  "slurm-platform" = FALSE,
                                  "google-batch" = FALSE,
                                  "azure-batch" = FALSE,
                                  safe_extract(json_data$computeEnv$config$forge, "gpuEnabled"))),
      ebs_autoscale = ifelse(is.null(json_data$computeEnv$platform), NA,
                             switch(json_data$computeEnv$platform,
                                    "slurm-platform" = FALSE,
                                    "google-batch" = FALSE,
                                    "azure-batch" = FALSE,
                                    safe_extract(json_data$computeEnv$config$forge, "ebsAutoScale"))),
      region = ifelse(is.null(json_data$computeEnv$platform), NA,
                      switch(json_data$computeEnv$platform,
                             "slurm-platform" = "NA",
                             "google-batch" = safe_extract(json_data$computeEnv$config, "location"),
                             "azure-batch" = safe_extract(json_data$computeEnv$config, "region"),
                             safe_extract(json_data$computeEnv$config, "region"))),
      waveEnabled = safe_extract(json_data$computeEnv$config, "waveEnabled"),
      fusion_enabled = safe_extract(json_data$computeEnv$config, "fusion2Enabled"),
      nvnmeStorageEnabled = safe_extract(json_data$computeEnv$config, "nvnmeStorageEnabled"),
      instanceTypes = ifelse(is.null(json_data$computeEnv$platform), NA,
                             switch(json_data$computeEnv$platform,
                                    "slurm-platform" = "HPC",
                                    "google-batch" = "",
                                    "azure-batch" = "",
                                    paste(safe_extract(json_data$computeEnv$config$forge, "instanceTypes", ""), collapse = ", ")))
    )
  })
  
  # Check if any of the data frames in the list are empty
  empty_dfs <- sapply(tw_run_dumps_launch, function(df) nrow(df) == 0)
  if (any(empty_dfs)) {
    warning(paste("Empty data frames found for RunIDs:", 
                  paste(log_files$RunID[empty_dfs], collapse = ", ")))
  }
  
  tw_run_dumps_launch_full <- rbindlist(tw_run_dumps_launch, fill = TRUE)
  tw_run_dumps_launch_full <- tw_run_dumps_launch_full %>% unique()
  
  ################
  #### TASK logs
  ## Read in the json files for each dir in unzipped files. Add the name of the dir as a column
  tw_run_dumps_tasks <- apply(log_files,1, function(row){
    task_log <- row["task_logs"]
    json_data <- jsonlite::fromJSON(task_log)
    json_data$RunID <- row["RunID"]
    json_data$Group = row["group"]
    json_data <- as.data.table(json_data)
  })
  tw_run_dumps_tasks_full <- rbindlist(tw_run_dumps_tasks, fill = TRUE)
  
  ################
  #### METADATA logs
  # Read in the json files for each dir in unzipped files. Add the name of the dir as a column
  tw_run_dumps_meta <- apply(log_files,1, function(row){
    meta_log <- row["meta_logs"]
    if(meta_log != ""){
      json_data <- jsonlite::fromJSON(meta_log)
      # Drop element "labels" from json_data as t his causes duplication of rows
      json_data$labels <- paste(json_data$labels$name, collapse = ",")
      json_data$RunID <- row["RunID"]
      json_data <- as.data.table(json_data)
    }
  })
  
  tw_run_dumps_meta_full <- rbindlist(tw_run_dumps_meta, fill = TRUE)

  return(list("workflow" = tw_run_dumps_workflow_full,
              "service" = tw_run_dumps_service_full,
              "load" = tw_run_dumps_load_full,
              "launch" = tw_run_dumps_launch_full,
              "workflow_tasks" = tw_run_dumps_tasks_full,
              "metadata" = tw_run_dumps_meta_full)
  )
}

## Theming function from Adam
seqera_light_theme <- function() {
  library(ggplot2)
  library(showtext)
  library(viridis)
  
  theme(
    plot.background = element_rect(fill = "#FFFFFF", color = NA), # Plot background (white)
    panel.background = element_rect(fill = "#FFFFFF", color = NA), # Panel background (white)
    panel.grid.major = element_line(color = "#d3d3d3", linetype = "dashed"), # Dashed major grid lines
    panel.grid.minor = element_blank(), # Remove minor grid lines
    panel.border = element_blank(), # Remove panel border
    
    # Text
    text = element_text(color = "#160F26"), # Default text color
    plot.title = element_text(size = 18, face = "bold", color = "#160F26", hjust = 0.5), # Title
    plot.subtitle = element_text(size = 14, color = "#7B7B7B", hjust = 0.5), # Subtitle
    axis.title = element_text(size = 12, face = "bold", color = "#160F26"), # Axis titles
    axis.text = element_text(size = 10, color = "#160F26"), # Axis text
    legend.title = element_text(size = 12, face = "bold", color = "#160F26"), # Legend title
    legend.text = element_text(size = 10, color = "#160F26"), # Legend text
    
    # Axis lines and ticks
    axis.line = element_line(color = "#160F26"), # Axis lines
    axis.ticks = element_line(color = "#160F26"), # Axis ticks
    
    # Legend
    legend.background = element_blank(), # Remove legend background
    legend.key = element_rect(fill = "#FFFFFF", color = NA), # Legend key background
    
    # Facet labels
    strip.background = element_rect(fill = "#160F26", color = NA), # Facet background color
    strip.text = element_text(size = 12, color = "#FFFFFF") # Facet label text color
  )
}

seqera_colour <- function(...) {
  seqera_colours <- c(
    `dark`       = "#160F26",
    `dark_gray`  = "#7B7B7B",
    `light_gray` = "#EAEBEB",
    `red`        = "#FA6863",
    `green`      = "#0DC09D",
    `blue`       = "#3D95FD",
    `orange`     = "#F18046",
    `fusion`     = "#FA6863",
    `nextflow`   = "#0DC09D",
    `wave`       = "#3D95FD",
    `multiqc`    = "#F18046"
  )
  cols <- c(...)
  if (is.null(cols))
    return (seqera_colours)
  seqera_colours[cols]
}

seqera_palette <- function(palette = "product", ...) {
  seqera_palettes <- list(
    `complete` = seqera_colour(),
    `background` = seqera_colour("dark", "dark_gray", "light_gray"),
    `product` = seqera_colour("nextflow", "fusion", "wave", "multiqc"),
    `fusion` = seqera_colour("fusion", "multiqc"),
    `nextflow` = seqera_colour("nextflow", "wave"),
    `wave` = seqera_colour("wave", "nextflow"),
    `multiqc` = seqera_colour("multiqc", "fusion")
  )
  return(seqera_palettes[[palette]])
}

palette_gen <- function(palette = "product", reverse = FALSE, ...) {
  pal <- seqera_palette(palette)
  pal <- if (reverse) rev(pal) else pal
  colorRampPalette(pal, ...)
}

scale_fill_seqera <- function(palette = "product", reverse = FALSE, ...) {
  ggplot2::discrete_scale(
    "fill", 'seqera',
    palette_gen(palette = palette, reverse = reverse),
    ...
  )
}

scale_discrete_seqera <- function(palette = "product", reverse = FALSE, ...) {
  ggplot2::discrete_scale(
    "colour", 'seqera',
    palette_gen(palette = palette, reverse = reverse),
    ...
  )
}

scale_continuous_seqera <- function(palette = "product", reverse = FALSE, ...) {
  pal <- palette_gen_c(palette = palette, reverse = reverse)
  scale_color_gradientn(colors = pal(256), ...)
}

## Function to create a badge in reactable
badge <- function(text, color = "#e8a87c") {
  library(htmltools)
  div(style = list(
    display = "inline-block",
    padding = "4px 12px",
    margin = "2px",
    color = "white",
    backgroundColor = color,
    borderRadius = "12px",
    fontSize = "14px",
    fontWeight = "bold",
    textAlign = "center",
    verticalAlign = "middle"
  ), text)
}

# Custom scale function to add buffer
expand_x_limits <- function(x) {
  rng <- range(x, na.rm = TRUE)
  buffer <- (rng[2] - rng[1]) * 0.2  # 20% buffer
  c(rng[1], rng[2] + buffer)
}

