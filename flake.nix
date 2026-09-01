{
  description = "redditctl development environment";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      supportedSystems = [
        "aarch64-darwin"
        "x86_64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
      pkgsFor = system: import nixpkgs { inherit system; };
      pythonFor =
        pkgs:
        pkgs.python313.withPackages (
          pythonPackages: with pythonPackages; [
            build
            coverage
            google-auth
            google-auth-oauthlib
            google-genai
            hatchling
            hypothesis
            httpx
            keyring
            mypy
            platformdirs
            pydantic
            pytest
            pytest-asyncio
            pytest-textual-snapshot
            respx
            starlette
            textual
            typer
            uvicorn
          ]
        );
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
          python = pythonFor pkgs;
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.gh
              pkgs.git
              pkgs.nixfmt
              pkgs.ripgrep
              pkgs.ruff
              pkgs.sqlite
            ];

            env = {
              PYTHONNOUSERSITE = "1";
              REDDITCTL_NIX_SHELL = "1";
            };

            shellHook = ''
              echo "redditctl development shell (Python ${python.pythonVersion})"
            '';
          };
        }
      );

      checks = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
          python = pythonFor pkgs;
        in
        {
          development-environment = pkgs.runCommand "redditctl-development-environment" { } ''
            ${python}/bin/python -c "import google.genai, google_auth_oauthlib, httpx, keyring, pydantic, textual, typer"
            touch $out
          '';
        }
      );

      formatter = forAllSystems (system: (pkgsFor system).nixfmt);
    };
}
