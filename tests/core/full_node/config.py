# flake8: noqa: E501
job_timeout = 60
CHECK_RESOURCE_USAGE = """
    - name: Check resource usage
      run: |
        sqlite3 -readonly -separator " " .pymon "select item,cpu_usage,total_time,mem_usage from TEST_METRICS order by mem_usage desc;" >metrics.out
        ./tests/check_pytest_monitor_output.py <metrics.out
"""
