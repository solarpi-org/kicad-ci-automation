{
  description = "KiCAD CI/CD automation for ERC, DRC, ODB++ export, and visual diffs";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    flake-utils.url = "github:numtide/flake-utils";
    kicad-diff = {
      url = "github:murdoa/KiCad-Diff/nix_kicad_9";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    sbomnix = {
      url = "github:tiiuae/sbomnix";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      kicad-diff,
      sbomnix,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        kicad = pkgs.kicad-small;
        kicad-diff-pkg = kicad-diff.packages.${system}.default;

        # Python environment for diff artifact generation and templating
        python-with-packages = pkgs.python3.withPackages (ps: with ps; [
          pillow
          reportlab
          pypdf2
        ]);

        # Package source so Nix store gets the kicad_ci module tree
        kicad-ci-src = pkgs.runCommand "kicad-ci-src" {} ''
          mkdir -p $out
          cp -r ${./src/kicad_ci} $out/kicad_ci
          cp ${./src/kicad_ci/cli.py} $out/generate-diff-artifacts.py
        '';

        generate-diff-artifacts = pkgs.writeShellScriptBin "generate-diff-artifacts" ''
          exec ${python-with-packages}/bin/python3 -c \
            "import sys; sys.path.insert(0, '${kicad-ci-src}'); from kicad_ci.cli import main; sys.exit(main())" \
            "$@"
        '';

        kicad-template = pkgs.writeShellScriptBin "kicad-template" ''
          exec ${python-with-packages}/bin/python3 ${./src/kicad-template.py} "$@"
        '';

        sbomnix-pkg = sbomnix.packages.${system}.default;

        generate-sbom = pkgs.writeShellApplication {
          name = "generate-sbom";
          runtimeInputs = [ sbomnix-pkg pkgs.coreutils ];
          text = ''
            outdir="''${1:-.}"
            mkdir -p "$outdir"

            # Cache key: the kicad-ci store path hash. Same closure = same SBOM.
            store_hash="$(basename "${kicad-ci}" | cut -d- -f1)"
            cache_marker="$outdir/.sbom-hash"

            if [[ -f "$cache_marker" ]] && [[ "$(cat "$cache_marker")" == "$store_hash" ]] \
               && [[ -f "$outdir/sbom.cdx.json" ]] \
               && [[ -f "$outdir/sbom.spdx.json" ]] \
               && [[ -f "$outdir/sbom.csv" ]]; then
              echo "SBOM up to date (kicad-ci hash: $store_hash), skipping generation"
              exit 0
            fi

            echo "Generating runtime SBOM for kicad-ci ($store_hash)..."
            sbomnix "''${FLAKE_REF:-.}#default" \
              --cdx "$outdir/sbom.cdx.json" \
              --spdx "$outdir/sbom.spdx.json" \
              --csv "$outdir/sbom.csv"
            echo -n "$store_hash" > "$cache_marker"
          '';
        };

        kicad-ci = pkgs.writeShellApplication {
          name = "kicad-ci";
          runtimeInputs = [
            kicad
            kicad-diff-pkg
            generate-diff-artifacts
            kicad-template
            pkgs.jq
            pkgs.coreutils
            pkgs.findutils
            pkgs.python3
            pkgs.inkscape  # for SVG to PDF conversion (preserves vectors)
            pkgs.poppler-utils  # for pdfunite and pdfinfo
            pkgs.ghostscript  # for PDF operations and cropping
          ];
          text = builtins.readFile ./src/kicad-ci.sh;
        };

      in
      {
        packages = {
          default = kicad-ci;
          kicad-ci = kicad-ci;
          generate-sbom = generate-sbom;
        };

        apps = {
          default = {
            type = "app";
            program = "${kicad-ci}/bin/kicad-ci";
          };
          kicad-ci = {
            type = "app";
            program = "${kicad-ci}/bin/kicad-ci";
          };
          generate-sbom = {
            type = "app";
            program = "${generate-sbom}/bin/generate-sbom";
          };
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            kicad
            kicad-diff-pkg
            kicad-ci
            pkgs.jq
          ];

          shellHook = ''
            echo "KiCAD CI/CD Development Environment"
            echo ""
            echo "Available tools:"
            echo "  kicad-cli  - KiCAD command-line interface"
            echo "  kicad-ci   - Run full CI/CD pipeline"
            echo "  kidiff     - KiCAD visual diff tool"
            echo ""
            echo "Usage:"
            echo "  kicad-ci --help"
            echo ""
          '';
        };
      }
    );
}
