# Github actions template config.
oses = ["ubuntu", "macos"]

# Defaults are conservative.
parallel = False
checkout_blocks_and_plots = True
install_timelord = False
job_timeout = 30
custom_vars = ["CHECK_RESOURCE_USAGE"]
