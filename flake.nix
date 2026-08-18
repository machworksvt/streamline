{
  description = "streamline — AeroDB producer for the Icarus chain: OpenVSP/VSPAERO campaigns, contract, release";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";

  outputs = { self, nixpkgs }:
    let
      # x86_64 only: the pinned OpenVSP is the official amd64 .deb (nix/openvsp.nix). Nothing in
      # this repo runs on the aircraft; it produces artifacts that icarus-dynamics pins.
      systems = [ "x86_64-linux" ];
      # OpenVSP is NASA Open Source Agreement 1.3 — OSI-approved, but nixpkgs files nasa13 as
      # unfree, so it has to be allowed by name. Only openvsp; nothing else unfree can slip in.
      pkgsFor = system: import nixpkgs {
        inherit system;
        config.allowUnfreePredicate = pkg:
          builtins.elem (nixpkgs.lib.getName pkg) [ "openvsp" ];
      };
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f (pkgsFor system));

      openvspFor = pkgs: pkgs.callPackage ./nix/openvsp.nix { };
    in {
      packages = forAllSystems (pkgs: rec {
        openvsp = openvspFor pkgs;
        default = openvsp;
      });

      devShells = forAllSystems (pkgs:
        let
          openvsp = openvspFor pkgs;
          # 3.12 because the OpenVSP Python module links libpython3.12 — see nix/openvsp.nix.
          python = pkgs.python312;
          openvspPy = python.pkgs.toPythonModule openvsp;
          pythonEnv = python.withPackages (ps: with ps; [
            openvspPy
            numpy
            matplotlib # the report stage; Agg only on the pipeline path
            casadi # ONLY for the contract's ingest-proof test (§2.6); the pipeline never imports it
            pytest
            jupyter # exploration notebooks (§8.4); CI smoke-executes them, output-stripped
          ]);
        in {
          default = pkgs.mkShell {
            name = "streamline";

            packages = [
              pythonEnv
              openvsp # vsp / vspaero / vspscript on PATH; the GUI is a design-time convenience
              pkgs.mesa # software GL for the GUI under WSLg (see the GL lines in shellHook)
              pkgs.gnumake
              pkgs.gcc # the contract's ingest proof compiles CasADi codegen with -std=c99
              pkgs.git
            ];

            shellHook = ''
              export STREAMLINE_ROOT="$PWD"
              export STREAMLINE_OPENVSP="${openvsp}"
              export STREAMLINE_OPENVSP_PINNED="${openvsp.pinnedVersion}"
              # SET, NOT APPENDED — same rule as the sibling repos. Inheriting the ambient
              # PYTHONPATH pulls an active conda environment's site-packages onto sys.path and the
              # environment stops being a function of flake.lock.
              export PYTHONPATH="$PWD/src:$PWD/contract"
              # Headless is the default everywhere (session.py sets openvsp_config before the
              # import); `streamline gui` flips it for one process. The GUI under WSL: nixpkgs' libglvnd cannot see the host's GL, so point it at
              # nixpkgs mesa and render with llvmpipe. Verified 2026-08-16 (WSLg): without these,
              # `vsp` prints "Insufficient GL support"; with them the 3D view works. Harmless on a
              # headless runner — nothing on the pipeline path touches GL.
              export LD_LIBRARY_PATH="${pkgs.mesa}/lib"
              export LIBGL_DRIVERS_PATH="${pkgs.mesa}/lib/dri"
              export LIBGL_ALWAYS_SOFTWARE=1
              export __GLX_VENDOR_LIBRARY_NAME=mesa
              echo "streamline dev shell — OpenVSP ${openvsp.pinnedVersion} (nix), python ${python.version}"
            '';
          };
        });
    };
}
