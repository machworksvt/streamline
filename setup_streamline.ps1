# setup_streamline.ps1

# Function to check if a conda environment exists by name.
function Test-CondaEnvExistence($envName) {
    $envList = conda env list | Out-String
    return $envList -match $envName
}

conda activate base

# Check if 'streamline' environment already exists.
if (Test-CondaEnvExistence "streamline") {
    $response = Read-Host "The 'streamline' environment already exists. Do you want to remove it and recreate it? (y/n)"
    if ($response -eq "y") {
        Write-Output "Removing existing 'streamline' environment..."
        conda env remove --name streamline --yes
    }
    else {
        Write-Output "Aborting setup. Please resolve the existing environment manually."
        exit
    }
}

# Check if 'vsppytools' exists from a previous OpenVSP setup.
if (Test-CondaEnvExistence "vsppytools") {
    $response = Read-Host "The 'vsppytools' environment exists. Do you want to remove it? (y/n)"
    if ($response -eq "y") {
        Write-Output "Removing existing 'vsppytools' environment..."
        conda env remove --name vsppytools --yes
    }
    else {
        Write-Output "Aborting setup. Please remove or rename 'vsppytools' manually."
        exit
    }
}

# Run the OpenVSP-provided setup script to create the OpenVSP environment.
Write-Output "Running the OpenVSP environment setup..."
Set-Location .\OpenVSP-3.42.3-win64\python
.\setup.ps1
Set-Location ..
Set-Location ..

# At this point, the openvsp script creates an environment called 'vsppytools'.
# Now, clone it to create a new environment called 'streamline'.
Write-Output "Cloning 'vsppytools' to create the 'streamline' environment..."
conda create --name streamline --clone vsppytools --yes

# Activate the 'streamline' environment.
Write-Output "Activating the 'streamline' environment..."
conda activate streamline

# Remove the original 'vsppytools' environment.
Write-Output "Removing the original 'vsppytools' environment..."
conda env remove --name vsppytools --yes

# Install additional required libraries.
Write-Output "Installing additional libraries..."
pip install -r requirements.txt

Write-Output "Setup complete! Your 'streamline' environment is now ready."
