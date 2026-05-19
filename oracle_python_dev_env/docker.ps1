# Docker to Podman shim for Windows
# This script redirects docker commands to podman running in WSL

$podmanDistro = "podman-machine-default"

# Forward all arguments to podman via WSL
& wsl.exe -d $podmanDistro podman @args
exit $LASTEXITCODE
