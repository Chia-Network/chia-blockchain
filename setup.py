from setuptools import setup

kwargs = dict(
    name="chia-blockchain",
    license="Apache License",
    python_requires=">=3.7, <4",
    install_requires=[
        "pytest",
        "pywin32",
    ],
    packages=[
        "chia",
    ],
)


if __name__ == "__main__":
    setup(**kwargs)  # type: ignore
