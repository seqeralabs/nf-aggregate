# install.packages("devtools")
# devtools::install_github("flowuenne/SeqeraBenchmarkR", auth_token = "<your-token>")

seqeraruncollection <- readRDS("tests/data/test_SeqeraRunCollection_object.rds")

output_path <- "tests/data/"
csv_path = paste0(output_path, "service_info",".csv")
data = as.matrix(seqeraruncollection@service_info)
write.csv(csv_path, )
