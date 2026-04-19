#' SeqeraPlatformRun Class
#'
#' @description An S4 class to represent a single pipeline run.
#'
#' @slot run_id Character string containing the run ID
#' @slot path Character string containing the path to run data
#' @slot pipeline Character string containing the pipeline name
#' @slot workflow_tasks Data frame containing workflow task information
#' @slot workflow_metrics Data frame containing workflow metrics
#' @slot machine_data Data frame containing optional machine-level metrics
#' @slot run_logs Data frame containing run logs
#'
#' @importFrom methods is slot slotNames
#' @export
setClass("SeqeraPlatformRun",
         slots = list(
           run_id = "character",
           path = "character",
           pipeline = "character",
           workflow_tasks = "data.frame",
           workflow_metrics = "data.frame",
           machine_data = "data.frame",
           run_logs = "data.frame"
         ))

#' Initialize method for SeqeraPlatformRun
#' 
#' @param .Object The SeqeraPlatformRun object to initialize
#' @param ... Additional arguments to initialize slots
setMethod("initialize", "SeqeraPlatformRun",
          function(.Object, ...) {
            # Call the parent initialize method
            .Object <- callNextMethod()
            
            # Get the list of provided arguments
            args <- list(...)
            
            # Define slot defaults
            slot_defaults <- list(
              workflow_tasks = data.frame(),
              workflow_metrics = data.frame(),
              machine_data = data.frame(),
              run_logs = data.frame(),
              run_id = character(0),
              path = character(0),
              pipeline = character(0)
            )
            
            # Assign defaults to slots if not provided
            for (slot_name in names(slot_defaults)) {
              if (is.null(args[[slot_name]])) {
                slot(.Object, slot_name) <- slot_defaults[[slot_name]]
              }
            }
            
            .Object
          })

#' Dollar operator for SeqeraPlatformRun objects
#'
#' Provides a convenient way to access slots of a SeqeraPlatformRun object using the $ operator.
#'
#' @param x A SeqeraPlatformRun object
#' @param name Character string naming the slot to access
#'
#' @return The contents of the requested slot
#'
#' @export
setMethod("$", "SeqeraPlatformRun",
          function(x, name) {
            if (name %in% slotNames(x)) {
              slot(x, name)
            } else {
              stop("Invalid slot name: ", name)
            }
          })
#' Internal function to remove prefixes from column names
#' 
#' @param names Character vector of column names to format
#' @return Character vector of formatted column names
#' @keywords internal
.removePrefixes <- function(names) {
  prefixes <- c(
    "service_info\\.", 
    "workflow_launch\\.", 
    "workflow_load\\.", 
    "workflow_metadata\\.",
    "workflow\\."
  )
  
  # Combine patterns with | (OR) operator
  pattern <- paste0("^(", paste(prefixes, collapse="|"), ")")
  
  # Remove the prefixes
  gsub(pattern, "", names)
}

#' Internal function to format column names in a SeqeraPlatformRun object
#' 
#' @param object A SeqeraPlatformRun object
#' @return The SeqeraPlatformRun object with formatted column names
#' @keywords internal
.formatColumnNames <- function(object) {
  if (nrow(object@run_logs) > 0) {
    colnames(object@run_logs) <- .removePrefixes(colnames(object@run_logs))
  }
  return(object)
}


# Update validity check
setValidity("SeqeraPlatformRun", function(object) {
  msgs <- NULL
  
  # Check run_id
  if (length(object@run_id) == 0 || nchar(object@run_id[1]) == 0) {
    msgs <- c(msgs, "run_id must not be empty")
  }
  
  # Check path
  if (length(object@path) == 0 || nchar(object@path[1]) == 0) {
    msgs <- c(msgs, "path must not be empty")
  }
  
  # Check pipeline
  if (length(object@pipeline) == 0 || nchar(object@pipeline[1]) == 0) {
    msgs <- c(msgs, "pipeline must not be empty")
  }
  
  # Check data frames
  df_slots <- c("workflow_tasks", "workflow_metrics", "machine_data", "run_logs")
  
  for (slot_name in df_slots) {
    df <- slot(object, slot_name)
    if (!is.data.frame(df)) {
      msgs <- c(msgs, sprintf("%s must be a data frame", slot_name))
    }
  }
  
  # Check run_logs
  if (!is.data.frame(object@run_logs)) {
    msgs <- c(msgs, "run_logs must be a data frame")
  }
  
  if (nrow(object@run_logs) > 0) {
    if (!"run_id" %in% colnames(object@run_logs)) {
      msgs <- c(msgs, "run_logs must have a run_id column")
    }
  }
  
  if (is.null(msgs)) TRUE else msgs
})
