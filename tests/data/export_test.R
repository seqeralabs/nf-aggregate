# install.packages("devtools")
# devtools::install_github("flowuenne/SeqeraBenchmarkR", auth_token = "<your-token>")

test_seqeraruncollection <- readRDS("tests/data/test_SeqeraRunCollection_object.rds")

output_path <- "tests/data/"
csv_path = paste0(output_path, "service_info",".csv")
data = as.matrix(seqeraruncollection@service_info)
write.csv(csv_path, )

library("dplyr")
test_df_1 <- full_join(test_seqeraruncollection@service_info,test_seqeraruncollection@workflow_load,by="run_id")
test_df_2 <- full_join(test_df_1,test_seqeraruncollection@workflow_metadata,by="run_id")
test_df_3 <- full_join(test_df_2,test_seqeraruncollection@workflow,by="run_id")
write.csv(file="tests/data/join_1.csv",test_df_1)
write.csv(file="tests/data/join_2.csv",test_df_2)
write.csv(file="tests/data/join_3.csv",test_df_3)
