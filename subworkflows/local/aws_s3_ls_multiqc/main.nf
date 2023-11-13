//
// Subworkflow with functionality to get file sizes on AWS
//

/*
========================================================================================
    IMPORT MODULES/SUBWORKFLOWS
========================================================================================
*/

include { AWS_S3_LS } from '../../../modules/local/aws_s3_ls'

/*
========================================================================================
    SUBWORKFLOW DEFINITION
========================================================================================
*/

workflow AWS_S3_LS_MULTIQC {

    take:
    buckets             // channel: [id, bucket]
    aws_account_id      //  string: AWS account number
    aws_role_name       //  string: AWS role name
    multiqc_header      //  string: header used in MultiQC report
    multiqc_file_prefix //  string: Filename prefix for MultiQC custom content file

    main:

    ch_versions = Channel.empty()

    //
    // MODULE: Get size of bucket on AWS
    //
    AWS_S3_LS (
        buckets,
        aws_account_id,
        aws_role_name
    )
    ch_versions = ch_versions.mix(AWS_S3_LS.out.versions.first())

    AWS_S3_LS
        .out
        .txt
        .map { 
            id, listing ->
                "${id}\t${getTotalBucketSize(listing).toBytes() / 1073741824}"
        }
        .collect()
        .map {
            return multiqcTsvFromList(it, multiqc_header)
        }
        .collectFile(name:"${multiqc_file_prefix}_mqc.tsv")
        .set { ch_bucket_size_multiqc }

    emit:
    bucket_files        = AWS_S3_LS.out.txt
    bucket_size_multiqc = ch_bucket_size_multiqc
    versions            = ch_versions
}

//
// Function to parse output of 'aws s3 ls' to get total size of bucket
//
def getTotalBucketSize(file) {
    def size = 0
    file.eachLine { line ->
        if (line.contains('Total Size:')) {
           size = line.split()[-1]
        }
    }
    return size as nextflow.util.MemoryUnit
}

//
// Create MultiQC tsv custom content from a list of values
//
def multiqcTsvFromList(tsv_data, header) {
    def tsv_string = ""
    if (tsv_data.size() > 0) {
        tsv_string =  ([ header ] + tsv_data).join('\n')
    }
    return tsv_string
}
