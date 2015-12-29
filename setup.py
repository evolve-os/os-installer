from setuptools import setup
            
setup(name         = 'os-installer',
      version      = '5.2',
      author       = "Ikey Doherty",
      author_email = "ikey@solus-project.com",
      license      = "GPL-2.0",
      packages     = ['os_installer', 'os_installer.pages'],
      scripts      = ['os-installer-gtk'],
)
