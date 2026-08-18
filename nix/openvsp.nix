# OpenVSP, pinned by hash, from the official Ubuntu 24.04 package (decision D2 — the .deb is
# wrapped rather than the source built; the properties decision #12 wanted are all here: one
# version, one hash, refuse-unpinned at session init, canonical campaigns only from this flake).
#
# What comes out:
#   $out/bin/{vsp,vspaero,vspscript,vspslicer,vspviewer,vsploads}   the binaries, patchelf'd
#   $out/lib/python3.12/site-packages/{openvsp,openvsp_config,degen_geom,utilities}
#                                                                   the Python API, importable by the
#                                                                   python312 this flake ships
#   $out/opt/OpenVSP/...                                            everything else the deb carried
#                                                                   (airfoil library, scripts, AvlPy,
#                                                                   CHARM, PyVSP — the AVL bridge is
#                                                                   here when a v1 backend wants it)
#
# The `openvsp` package finds its own `vspaero` next to `__init__.py` (setup_vspaero_path), so the
# bundled solver copy inside the package is the one the API runs — it is byte-identical to the
# top-level one and both are patched.
#
# Bumping: change `version` and `sha256`, `nix build .#openvsp`, then re-run the golden reference
# project (§8.9 #4) and review the diff. There is no other supported way to move the solver.
{ lib, stdenv, fetchurl, dpkg, autoPatchelfHook, python312, libxml2, cminpack, glew, libGL, libGLU
, xorg }:

let
  # OpenVSP was linked against Ubuntu's libxml2 2.9, which still exports the legacy nanoHTTP
  # API; nixpkgs' 2.13 leaves it out by default and the GUI binary then dies at load with
  # `undefined symbol: xmlNanoHTTPMethod`. The headless module happens not to bind it, but one
  # libxml2 with the symbol present serves both, so it is enabled here rather than special-cased.
  libxml2Http = libxml2.override { enableHttp = true; };
in
stdenv.mkDerivation rec {
  pname = "openvsp";
  version = "3.51.2";

  src = fetchurl {
    # openvsp.org moves a release from zips/current/ to zips/old/ when the next one ships. Both
    # spellings are listed so the pin survives that move; the hash is what actually pins it.
    urls = [
      "https://openvsp.org/download.php?file=zips/current/linux/OpenVSP-${version}-Ubuntu-24.04_amd64.deb"
      "https://openvsp.org/download.php?file=zips/old/linux/OpenVSP-${version}-Ubuntu-24.04_amd64.deb"
    ];
    name = "OpenVSP-${version}-Ubuntu-24.04_amd64.deb";
    sha256 = "da7f40856e0c905bc6bb32bee83f7a1096c5a714c7f5398405c594e8639dace5";
  };

  nativeBuildInputs = [ dpkg autoPatchelfHook ];

  # Everything the deb's Depends: line names, from nixpkgs. libgomp (vspaero is OpenMP) and
  # libstdc++ come from the compiler's lib output. The Python ABI is 3.12 — the .so links
  # libpython3.12.so.1.0 — which is why the flake's interpreter is python312 and nothing else.
  buildInputs = [
    python312
    libxml2Http
    cminpack
    glew
    libGL
    libGLU
    xorg.libX11
    stdenv.cc.cc.lib
  ];

  dontConfigure = true;
  dontBuild = true;

  unpackPhase = ''
    dpkg-deb -x "$src" .
  '';

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/opt" "$out/bin" "$out/${python312.sitePackages}"
    cp -r opt/OpenVSP "$out/opt/OpenVSP"

    for b in vsp vspaero vspscript vspslicer vspviewer vsploads; do
      if [ -e "$out/opt/OpenVSP/$b" ]; then
        ln -s "$out/opt/OpenVSP/$b" "$out/bin/$b"
      fi
    done

    # The importable packages, copied (not symlinked) so `openvsp.__file__` is a real path and
    # setup_vspaero_path finds the bundled solver beside it.
    for p in openvsp openvsp_config degen_geom utilities; do
      cp -r "$out/opt/OpenVSP/python/$p/$p" "$out/${python312.sitePackages}/$p"
    done
    runHook postInstall
  '';

  # autoPatchelf must not choke on the graphics module when a headless consumer never loads it;
  # it is patched like everything else, and the GUI deps are in buildInputs so it resolves too.
  autoPatchelfIgnoreMissingDeps = [ ];

  passthru = {
    pinnedVersion = version;
    # For python312.pkgs.toPythonModule — lets `python.withPackages (ps: [ openvsp ])` work.
    pythonModule = python312;
  };

  meta = with lib; {
    description = "OpenVSP ${version} — parametric aircraft geometry + VSPAERO, official Ubuntu build";
    homepage = "https://openvsp.org";
    license = licenses.nasa13;
    platforms = [ "x86_64-linux" ];
  };
}
