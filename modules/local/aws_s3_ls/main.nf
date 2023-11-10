process AWS_S3_LS {
    tag "$id"
    secret 'AWS_ACCESS_KEY_ID'
    secret 'AWS_SECRET_ACCESS_KEY'
    conda 'awscli=2.13.32 jq=1.6'

    input:
    tuple val(id), val(bucket)
    val account_id
    val role_name

    output:
    tuple val(id), path("*.txt"), emit: txt
    path "versions.yml"         , emit: versions

    script:
    def args = task.ext.args ?: ''
    def prefix = task.ext.prefix ?: "${id}"
    // Solution found from: https://stackoverflow.com/a/69513834
    """
    OUT=\$(aws sts assume-role --role-arn arn:aws:iam::${account_id}:role/${role_name} --role-session-name aaa);\
    export AWS_ACCESS_KEY_ID=\$(echo \$OUT | jq -r '.Credentials''.AccessKeyId');\
    export AWS_SECRET_ACCESS_KEY=\$(echo \$OUT | jq -r '.Credentials''.SecretAccessKey');\
    export AWS_SESSION_TOKEN=\$(echo \$OUT | jq -r '.Credentials''.SessionToken');

    aws \\
        s3 \\
        ls \\
        $args \\
        $bucket \\
        > ${prefix}.txt

    cat <<-END_VERSIONS > versions.yml
    "${task.process}":
        aws-cli: \$(aws --version | awk -F/ '{print \$2}' | awk '{print \$1}')
    END_VERSIONS
    """
}
