## Environment Setup

Streamline is designed to run on Windows with [Anaconda](https://www.anaconda.com/download) (or Miniconda) installed. You **must** have Anaconda available on your system before proceeding.

### 1. Install Anaconda

Download and install [Anaconda](https://www.anaconda.com/download).  
During installation, make sure to:

- Add Anaconda to your PATH (or run `conda init powershell` after install).
- Restart PowerShell so `conda` is available.

You can verify with:

```powershell
conda --version
```
### 2. Run the setup script
From the repo root, run:
```powershell
.\setup_streamline.ps1
```
This script will
- Install the OpenVSP bindings for python
- Create a conda environment called `streamline`
- Install all the requirments from `requirements.txt`
- Check that the `openvsp` package imported properly

If you’ve previously created the environment and want a clean rebuild, run with:
```powershell
.\setup_streamline.ps1 -Force
```
If you have any issues with this script, message Nathan on slack.

### 3. Activate the environment
To activate the enviroment you just created (allowing your python scripts to actually use the openvsp and other packages) run:
```powershell
conda activate streamline
```

### I need to add a new python package
Add your python package to `requirements.txt` and run the setup again:
```powershell
.\setup_streamline.ps1 -Force
```
Make sure to alert your team members so that they also re-run the setup script after pulling in your changes.