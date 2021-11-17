# Github actions template config.
oses = ["ubuntu", "macos"]

# Defaults are conservative.
parallel = True
checkout_blocks_and_plots = True
install_timelord = True
job_timeout = 30
custom_vars = ["CHECK_RESOURCE_USAGE"]
