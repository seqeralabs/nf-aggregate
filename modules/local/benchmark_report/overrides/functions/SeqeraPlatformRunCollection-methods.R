# Generic function definitions
#' Get run IDs from a collection
#' @param object SeqeraPlatformRunCollection object
#' @return Character vector of run IDs
#' @export
setGeneric("getRunIds", function(object) standardGeneric("getRunIds"))

#' Get pipeline names from a collection
#' @param object SeqeraPlatformRunCollection object
#' @return Character vector of pipeline names
#' @export
setGeneric("getPipelines", function(object) standardGeneric("getPipelines"))

#' Get group from a collection
#' @param object SeqeraPlatformRunCollection object
#' @return Character vector of group labels
#' @export
setGeneric("getGroups", function(object) standardGeneric("getGroups"))

#' Get workflow data from a collection
#' @param object SeqeraPlatformRunCollection object
#' @param slot_name Character string specifying which slot to get. Must be one of "workflow_metrics", "workflow_tasks", "machine_data", or "run_logs"
#' @return Combined data frame of the requested workflow data
#' @export
setGeneric("getWorkflowData", function(object, slot_name) standardGeneric("getWorkflowData"))

#' Generate a summary message for a SeqeraPlatformRunCollection
#'
#' @description Creates a formatted summary message describing the number of pipeline 
#' executions and groups in the collection.
#'
#' @param object A SeqeraPlatformRunCollection object
#' @return A character string containing the formatted summary message
#'
#' @export
setGeneric("generateReportSummaryMessage", 
           function(object) standardGeneric("generateReportSummaryMessage"))

#' Create HTML link for run ID
#' @param run_id Character string of run ID
#' @param url_table Data frame with run_id and runUrl columns
#' @return HTML string for link or original run_id if no URL found
#' @keywords internal
.create_link <- function(run_id, url_table) {
  if (is.na(run_id)) return("")
  url <- url_table$runUrl[url_table$run_id == run_id]
  if (length(url) == 0) return(run_id)
  sprintf('<a href="%s" target="_blank">%s</a>', url, run_id)
}

#' Generate overview table for SeqeraPlatformRunCollection
#'
#' @description Creates a reactable table showing pipeline executions by group
#' with clickable run IDs linking to the Nextflow Tower URLs.
#'
#' @param object A SeqeraPlatformRunCollection object
#' @return A reactable object displaying the overview table
#'
#' @importFrom dplyr select filter mutate
#' @importFrom tidyr pivot_wider
#' @importFrom reactable reactable colDef
#' @export
setGeneric("generateReactOverviewTable", 
           function(object) standardGeneric("generateReactOverviewTable"))

# Method implementations
#' Initialize method for SeqeraPlatformRunCollection
#' @rdname initialize-SeqeraPlatformRunCollection-method
setMethod("initialize", "SeqeraPlatformRunCollection", function(.Object, ...) {
  args <- list(...)
  
  # First handle the list part
  if (length(args) > 0 && !is.null(names(args)) && "runs" %in% names(args)) {
    # If runs is provided as a named argument
    runs <- args$runs
  } else {
    # If runs are provided as unnamed arguments
    runs <- args[!names(args) %in% c("Class", "group")]
  }
  
  # Convert runs to a list if it isn't already
  if (!is.list(runs)) {
    runs <- list(runs)
  }
  
  # Initialize the list part directly
  for (i in seq_along(runs)) {
    .Object[[i]] <- runs[[i]]
  }
  
  # Handle group after list initialization
  if ("group" %in% names(args) && !is.null(args$group)) {
    .Object@group <- as.character(args$group)
  } else {
    # Default to empty strings matching the length of runs
    .Object@group <- rep("", length(runs))
  }
  
  return(.Object)
})

# Accessor method implementations
setMethod("getRunIds", "SeqeraPlatformRunCollection", function(object) {
  sapply(object, function(x) x@run_id)
})

setMethod("getPipelines", "SeqeraPlatformRunCollection", function(object) {
  sapply(object, function(x) x@pipeline)
})

#' Get workflow data from a collection
#' @param object SeqeraPlatformRunCollection object
#' @param slot_name Character string specifying which slot to get. Must be one of "workflow_metrics", "workflow_tasks", "machine_data", or "run_logs"
#' @return Combined data frame of the requested workflow data
#' @export
setMethod("getWorkflowData", "SeqeraPlatformRunCollection", function(object, slot_name) {
  # Validate slot_name
  valid_slots <- c("workflow_metrics", "workflow_tasks", "machine_data", "run_logs")
  if (!slot_name %in% valid_slots) {
    stop(sprintf("slot_name must be one of: %s", paste(valid_slots, collapse = ", ")))
  }
  
  # Extract data from each run and add run_id and group columns
  data_list <- lapply(seq_along(object), function(i) {
    run <- object[[i]]
    df <- as.data.frame(slot(run, slot_name))  # Ensure it's a data frame
    
    if (nrow(df) > 0) {
      # Add run_id and group columns
      df$run_id <- run@run_id
      df$group <- object@group[i]
      return(df)
    } else {
      return(NULL)
    }
  })
  
  # Remove NULL entries
  data_list <- data_list[!sapply(data_list, is.null)]
  
  # If no data was found, return empty data frame
  if (length(data_list) == 0) {
    return(data.frame())
  }
  
  # Check and harmonize column types across all data frames
  all_cols <- unique(unlist(lapply(data_list, colnames)))
  
  # Get column types from first data frame as reference
  ref_types <- sapply(data_list[[1]], class)
  
  # Harmonize column types across all data frames
  data_list <- lapply(data_list, function(df) {
    for (col in all_cols) {
      if (col %in% names(df)) {
        # If column exists in reference, match its type
        if (col %in% names(ref_types)) {
          target_type <- ref_types[col]
          # Convert column to match reference type
          tryCatch({
            if (class(df[[col]]) != target_type) {
              df[[col]] <- switch(target_type,
                                "numeric" = as.numeric(df[[col]]),
                                "integer" = as.integer(df[[col]]),
                                "character" = as.character(df[[col]]),
                                "factor" = as.factor(df[[col]]),
                                df[[col]])  # default: keep original
            }
          }, error = function(e) {
            warning(sprintf("Could not convert column '%s' to type '%s'. Keeping original type.", 
                          col, target_type))
          })
        }
      } else {
        # Add missing column with NA of appropriate type
        df[[col]] <- NA
        if (col %in% names(ref_types)) {
          df[[col]] <- switch(ref_types[col],
                            "numeric" = as.numeric(NA),
                            "integer" = as.integer(NA),
                            "character" = as.character(NA),
                            "factor" = as.factor(NA),
                            NA)
        }
      }
    }
    return(df)
  })
  
  # Use bind_rows to combine data frames
  combined_df <- dplyr::bind_rows(data_list)
  
  # Ensure run_id and group are the first columns
  col_order <- c("run_id", "group", 
                 setdiff(colnames(combined_df), c("run_id", "group")))
  combined_df <- combined_df[, col_order]
  
  return(combined_df)
})

setMethod("getGroups", "SeqeraPlatformRunCollection", function(object) {
  object@group
})

#' Length method for SeqeraPlatformRunCollection
#' @param x SeqeraPlatformRunCollection object
#' @return Number of runs in the collection
#' @export
setMethod("length", "SeqeraPlatformRunCollection", function(x) {
  length(as(x, "list"))
})

#' Subsetting method for SeqeraPlatformRunCollection
#' @param x SeqeraPlatformRunCollection object
#' @param i index
#' @return SeqeraPlatformRun object or SeqeraPlatformRunCollection for multiple indices
#' @export
setMethod("[", "SeqeraPlatformRunCollection", function(x, i) {
  if (length(i) == 1) {
    return(as(x, "list")[[i]])
  }
  new("SeqeraPlatformRunCollection",
      runs = as(x, "list")[i])
}) 

#' Show method for SeqeraPlatformRunCollection objects
#'
#' @description Displays a formatted summary of a SeqeraPlatformRunCollection object, including:
#' \itemize{
#'   \item Number of runs and unique pipelines
#'   \item List of runs with their pipeline assignments and groups
#' }
#'
#' @param object A SeqeraPlatformRunCollection object to display
#' @return Invisibly returns the object while printing its summary to the console
#' @export
setMethod("show", "SeqeraPlatformRunCollection", function(object) {
  # Get run IDs and pipelines using accessor functions
  run_ids <- getRunIds(object)
  pipelines <- getPipelines(object)
  group <- object@group
  
  cat("## An object of class SeqeraPlatformRunCollection\n")
  cat(sprintf("## %d runs across %d unique pipelines\n", 
              length(run_ids), 
              length(unique(pipelines))))
  
  # Show run IDs with their corresponding pipelines and group
  cat("## Runs:\n")
  max_id_length <- max(nchar(run_ids)) + 2
  max_pipeline_length <- max(nchar(pipelines)) + 2
  
  for (i in seq_along(run_ids)) {
    group_info <- if (length(group) > 0 && !is.na(group[i]) && group[i] != "") 
      sprintf(" [Group: %s]", group[i]) else ""
    cat(sprintf("##  %-*s: %s%s\n", 
                max_id_length, 
                run_ids[i], 
                pipelines[i],
                group_info))
  }
  
  invisible(object)
})

#' @rdname generateReportSummaryMessage
setMethod("generateReportSummaryMessage", "SeqeraPlatformRunCollection",
          function(object) {
            # Get run logs data
            run_logs <- getWorkflowData(object, "run_logs")
            
            # Calculate unique pipeline executions and groups
            pipeline_exec <- length(unique(run_logs$run_id))
            groups <- unique(run_logs$group)
            
            # Create summary message
            summary_message <- paste(
              "This report summarizes the run, process, task, and, if applicable,",
              "cost metrics for", pipeline_exec, "pipeline executions, which have",
              "been split into", length(groups), "groups:",
              sep=" "
            )
            
            # Format groups string
            groups_string <- paste(
              sprintf("**%s**", groups),
              collapse=",\t"
            )
            
            # Combine messages
            paste(summary_message, groups_string, sep="\n")
          })

#' @rdname generateReactOverviewTable
setMethod("generateReactOverviewTable", "SeqeraPlatformRunCollection",
          function(object) {
            # Get run logs data
            merged_logs <- getWorkflowData(object, "run_logs")
            run_lookup <- data.frame(
              pipeline = getPipelines(object),
              run_id = getRunIds(object),
              group = getGroups(object),
              stringsAsFactors = FALSE
            )
            
            # Create URL lookup table
            url_table <- merged_logs %>% 
              dplyr::select(dplyr::any_of(c("run_id", "runUrl"))) %>%
              distinct()
            if (!"runUrl" %in% names(url_table)) {
              url_table$runUrl <- run_lookup$run_id
            }
            
            # Create overview dataframe
            overview_df <- run_lookup %>%
              dplyr::filter(rowSums(is.na(.)) == 0) %>%
              distinct() %>%
              # Extract repo name, keeping nf-core prefix if present
              dplyr::mutate(pipeline = ifelse(
                grepl("/nf-core/", pipeline),
                sub(".*/nf-core/([^/]+)$", "nf-core/\\1", pipeline),
                sub(".*/([^/]+)$", "\\1", pipeline)
              )) %>%
              pivot_wider(names_from = group, values_from = run_id)
            
            # Define column definitions for reactable
            columns_to_link <- setdiff(names(overview_df), "pipeline")
            
            column_defs <- lapply(names(overview_df), function(col) {
              if (col %in% columns_to_link) {
                colDef(
                  cell = function(value) {
                    .create_link(value, url_table)
                  },
                  html = TRUE
                )
              } else {
                colDef(name = "Pipeline name")
              }
            })
            names(column_defs) <- names(overview_df)
            
            # Create and return reactable
            reactable(
              overview_df,
              fullWidth = FALSE,
              wrap = TRUE,
              defaultColDef = colDef(minWidth = 200),
              columns = column_defs
            )
          })
