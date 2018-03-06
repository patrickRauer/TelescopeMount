from setuptools import setup

setup(
    name='Mount',
    version='0.8',
    packages=['MountTEST', 'MountTEST.core'],
    url='',
    license='GPL',
    author='Patrick Rauer',
    author_email='j.p.rauer@sron.nl',
    description='Mount control via ascom and direct communication',
    install_requires=['comtypes', 'pytz', 'numpy',
                      'serial', 'astropy']
)
