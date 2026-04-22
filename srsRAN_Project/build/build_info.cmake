
execute_process(
COMMAND git rev-parse --abbrev-ref HEAD
WORKING_DIRECTORY "/home/ubuntu/5G_Workspace/srsRAN_Project"
OUTPUT_VARIABLE GIT_BRANCH
OUTPUT_STRIP_TRAILING_WHITESPACE
)

execute_process(
COMMAND git log -1 --format=%h
WORKING_DIRECTORY "/home/ubuntu/5G_Workspace/srsRAN_Project"
OUTPUT_VARIABLE GIT_COMMIT_HASH
OUTPUT_STRIP_TRAILING_WHITESPACE
)

message(STATUS "Generating build information")
configure_file(
  /home/ubuntu/5G_Workspace/srsRAN_Project/lib/support/versioning/hashes.h.in
  /home/ubuntu/5G_Workspace/srsRAN_Project/build/hashes.h
)
