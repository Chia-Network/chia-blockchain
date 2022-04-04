from setuptools import setup

dependencies = [
    "pywin32",
]

dev_dependencies = [
    "pytest",
]

kwargs = dict(
    name="chia-blockchain",
    license="Apache License",
    python_requires=">=3.7, <4",
    install_requires=dependencies,
    packages=[
        "chia",
    ],
)


if __name__ == "__main__":
    setup(**kwargs)  # type: ignore
