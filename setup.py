from setuptools import setup, find_packages

setup(
    name="hgpatcher",
    description="Repackaging of Mercurial's patch code",
    version="0.1",
    url="http://code.google.com/p/python-patch/",
    license="GPL",
    packages=find_packages(),
    setup_requires=['nose>=0.11'],
    test_suite="nose.collector",
)
