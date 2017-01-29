# Eunomia

## What is this?

Eunomia is a simple tool to define batch jobs and run them within AWS.

## How does it work?

Eunomia utilises Step Functions, Lambda, S3, SNS, IAM, and CloudWatch Events to take a single yaml file and convert it into an autonomous batch job.  At the present time the set of helpers available for your batch definition is limited but easily extended by using the example_helper as a template.  You can also reference entirely distinct lambda functions if the input/outputs match the expected form.

It is presumed that in the majority of cases your batch job would be triggering distinct webservices hence the primary inclusion of the remote_uri_call function.  However, ssh support is also available for traditional connectivity.

The resulting output JSON from the batch is sent to a default SNS topic in your chosen region and hence downstream subscriptions can be formed as needed.

## Supported Task Types

* remote_uri_call (synchronously make a remote call over http)
* remote_ssh_call (synchronously make a remote call over ssh)
* start_batch (asynchronously execute another eunomia batch)

## Examples

The simplest example of a batch definition is:

```
name: Hello World
version: 1
execute: "rate(10 hours)"
start_at: step_1
tasks:
  step_1:
    type: remote_uri_call
    options:
        uri: http://github.com/kieranbroadfoot
        operation: GET
    on_success: step_2
  step_2:
    type: end
```

In this case a new state machine is created as Hello_World_v1 and an associated CloudWatch Event is triggered every ten hours to initiate the job.  The input set necessary to execute the batch is stored in a distinct S3 bucket.

The remote_uri_call helper can take a number of other arguments to set the values being passed to the remote service and the consumption of returning results.  This can be achieved as:

```
  step_1:
    type: remote_uri_call
    options:
        uri: http://jsonplaceholder.typicode.com/posts
        operation: POST
        payload: "{ 'userId': 99, 'id': 999, 'title': 'This is a title', 'body': 'This is a body' }"
        output_type: json
        output_format: {"post_id":"id"}
```

or:

```
  step_4:
    # get HEAD and parse using regexes, grouping works but multiple groups will create element_X
    type: remote_uri_call
    options:
        uri: http://kieranbroadfoot.com
        operation: HEAD
        output_type: text
        output_format: { "serverType": "Server: (.*)", "contentLength": "Content-Length:.*" }
```

If no output_format is included then the full result of call is included into a raw_output element in the batch output

## Execution

The "execute" element of the definition can either define a linked batch job or utilise the standard CloudWatch Events schedule format.  Examples include:

```
batch(Daily Batch 1) // execute Daily_Batch v1 on completion
cron(0 20 * * ? *) // every day at 8pm
rate(5 minutes)
```

Further details of CloudWatch schedule formats can be found [here](http://docs.aws.amazon.com/AmazonCloudWatch/latest/events/ScheduledEvents.html)

## SSH Support

Support for SSH requires the creation of secrets.  Whilst you may also create multiple types of secrets the primary goal is to store ssh private keys in the eunomia system.  These are envelope wrapped using KMS and stored in S3.  They can only be decrypted if a user has access to both the S3 bucket and KMS IAM permissions.  Do not utilise ssh keys which are password protected.

```
eunomia secrets add name_of_key -f /path/to/private_ssh_key

```

Once stored in Eunomia the format for a remote SSH call is as follows:

```
  step_1:
    type: remote_ssh_call
    options:
        user: ec2-user
        host: 10.10.10.10
        command: cat /etc/hosts
        secret: name_of_key
        output_type: text
        output_format: { "local": "10.*" }
```

## Setup

0. Install any dependencies in your local python installation (boto3)
1. Ensure your ~/.aws directory is setup with appropriate credentials (eunomia needs admin priv to setup)
2. Within the directory where the "helpers" directory is run: eunomia.py setup all
3. Lambda function creation must be undertaken on a Linux device due to the need for compiled components

It should be noted that additional regions can be configured by calling: "eunomia.py setup region"

## Usage
```
usage: eunomia.py [-h] [-r REGION] {list,generate,execute,delete,setup} ...

A simple batch scheduler

positional arguments:
  {list,generate,execute,delete,setup}
                        Try commands like "eunomia generate -h" or
                        "eunomia execute --help" to get each sub
                        command's options
    list                list available configurations
    generate            generate a batch definition
    execute             manually execute a batch definition
    delete              delete a batch definition
    setup               setup the Eunomia batch service
    secret              configure secrets for Eunomia batch service


optional arguments:
  -h, --help            show this help message and exit
  -r REGION, --region REGION
                        the AWS region to use
```