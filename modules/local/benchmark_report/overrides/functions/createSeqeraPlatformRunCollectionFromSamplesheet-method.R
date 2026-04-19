#' Create a SeqeraPlatformRunCollection from a samplesheet
#'
#' This function reads a samplesheet using fread, creates SeqeraPlatformRun objects
#' for each row, and combines them into a SeqeraPlatformRunCollection object.
#'
#' @param samplesheet_path The file path to the samplesheet CSV file.
#'
#' @return A SeqeraPlatformRunCollection object containing the SeqeraPlatformRun objects.
#'
#' @details The samplesheet must contain a 'file_path' column. If a 'group' column
#' is present, its values will be used to assign group to the runs.
#'
#' @importFrom data.table fread
#' @export
createSeqeraPlatformRunCollectionFromSamplesheet <- function(samplesheet_path) {
  samplesheet <- fread(samplesheet_path)
  
  if (nrow(samplesheet) == 0) {
    stop("Samplesheet is empty")
  }
  
  if (!"file_path" %in% names(samplesheet)) {
    stop("Samplesheet must contain a 'file_path' column")
  }
  
  # Extract group if present
  group <- if ("group" %in% names(samplesheet)) {
    as.character(samplesheet$group)
  } else {
    NULL
  }
  
  # Create SeqeraPlatformRun objects
  seqera_runs <- lapply(seq_len(nrow(samplesheet)), function(i) {
    file_path <- samplesheet$file_path[i]
    machines_path <- if ("machines_path" %in% names(samplesheet)) samplesheet$machines_path[i] else NA_character_
    if (is.na(machines_path) || machines_path == "") {
      machines_path <- NULL
    }
    createSeqeraPlatformRun(file_path, machines_path = machines_path)
  })
  
  # Create collection using the runs list and group
  createSeqeraPlatformRunCollection(
    runs = seqera_runs,
    group = group
  )
}
