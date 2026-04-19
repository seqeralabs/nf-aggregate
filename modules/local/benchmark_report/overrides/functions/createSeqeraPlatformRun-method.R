#' Create a SeqeraPlatformRun object
#'
#' @param input_path Path to either a tar.gz archive or a directory containing JSON files
#' @param machines_path Optional path to a machine metrics CSV associated with the run
#'
#' @return A SeqeraPlatformRun object
#' @export
#'
#' @examples
#' \dontrun{
#' run <- createSeqeraPlatformRun("path/to/run/folder")
#' }
createSeqeraPlatformRun <- function(input_path, machines_path = NULL) {
  if (!file.exists(input_path)) {
    stop("Input path does not exist")
  }
  if (!is.null(machines_path) && !file.exists(machines_path)) {
    stop("Machine metrics path does not exist")
  }
  
  # Get the run_id from the input path
  run_id <- basename(tools::file_path_sans_ext(input_path))
  if (grepl("\\.tar\\.gz$", input_path)) {
    run_id <- basename(tools::file_path_sans_ext(tools::file_path_sans_ext(input_path)))
  }
  
  # Handle tar.gz files
  if (grepl("\\.tar\\.gz$", input_path)) {
    temp_dir <- tempfile()
    dir.create(temp_dir)
    untar(input_path, exdir = temp_dir)
    working_path <- temp_dir
  } else {
    working_path <- input_path
  }
  
  # Function to safely read JSON and convert to data.frame
  safe_read_json <- function(filepath) {
    if (file.exists(filepath)) {
      content <- jsonlite::fromJSON(filepath)
      
      # If content is already a data.frame, return it
      if (is.data.frame(content)) {
        return(content)
      }
      
      # If content is a list, try to convert it to a data.frame
      if (is.list(content)) {
        # If the list has length 1 and contains a data.frame, extract it
        if (length(content) == 1 && is.data.frame(content[[1]])) {
          return(content[[1]])
        }
        
        # Try to convert list to data.frame
        tryCatch({
          # Handle nested lists by converting them to JSON strings
          content <- rapply(content, function(x) {
            if (is.list(x)) jsonlite::toJSON(x) else x
          }, how = "replace")
          
          # Convert to data.frame
          df <- as.data.frame(t(unlist(content)), stringsAsFactors = FALSE)
          return(df)
        }, error = function(e) {
          # If conversion fails, return empty data.frame with original as json column
          data.frame(
            json = jsonlite::toJSON(content, auto_unbox = TRUE),
            stringsAsFactors = FALSE
          )
        })
      }
    }
    data.frame() # Return empty data.frame if file doesn't exist
  }

  safe_read_machine_csv <- function(filepath) {
    if (is.null(filepath) || is.na(filepath) || filepath == "" || !file.exists(filepath)) {
      return(data.frame())
    }

    tryCatch({
      df <- data.table::fread(filepath, data.table = FALSE)
      if (!is.data.frame(df)) {
        return(data.frame())
      }
      df
    }, error = function(e) {
      stop(sprintf("Failed to read machine metrics CSV '%s': %s", filepath, e$message))
    })
  }
  
  # Read all log files
  log_files <- list(
    service_info = safe_read_json(file.path(working_path, "service-info.json")),
    workflow_launch = safe_read_json(file.path(working_path, "workflow-launch.json")),
    workflow_load = safe_read_json(file.path(working_path, "workflow-load.json")),
    workflow_metadata = safe_read_json(file.path(working_path, "workflow-metadata.json")),
    workflow = safe_read_json(file.path(working_path, "workflow.json"))
  )
  
  # Check if all data frames have exactly one row
  rows <- sapply(log_files, nrow)
  if (any(rows > 1)) {
    stop("One or more log files have multiple rows. Expected exactly one row per file:\n",
         paste(names(rows[rows > 1]), collapse = ", "))
  }
  
  # Handle duplicate column names by adding prefixes
  all_cols <- unlist(lapply(log_files, colnames))
  dup_cols <- all_cols[duplicated(all_cols)]
  if (length(dup_cols) > 0) {
    for (df_name in names(log_files)) {
      cols <- colnames(log_files[[df_name]])
      dup_in_df <- cols[cols %in% dup_cols]
      if (length(dup_in_df) > 0) {
        new_names <- paste(df_name, dup_in_df, sep = "_")
        colnames(log_files[[df_name]])[cols %in% dup_cols] <- new_names
      }
    }
  }
  
  # Combine all log files into run_logs
  run_logs <- do.call(cbind, log_files)
  run_logs$run_id <- run_id
  
  # Extract pipeline information
  pipeline <- if ("repository" %in% names(log_files$workflow)) {
    as.character(log_files$workflow$repository[1])
  } else {
    ""
  }
  
  # Create the main S4 object
  run_obj <- methods::new("SeqeraPlatformRun",
                         run_id = run_id,
                         path = working_path,
                         pipeline = pipeline,
                         workflow_tasks = safe_read_json(file.path(working_path, "workflow-tasks.json")),
                         workflow_metrics = safe_read_json(file.path(working_path, "workflow-metrics.json")),
                         machine_data = safe_read_machine_csv(machines_path),
                         run_logs = run_logs)
  
  # Format column names
  run_obj <- .formatColumnNames(run_obj)
  
  # Clean up temporary directory if we created one
  if (exists("temp_dir")) {
    unlink(temp_dir, recursive = TRUE)
  }
  
  return(run_obj)
}
