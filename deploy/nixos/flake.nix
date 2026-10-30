{
  description = "arbiter boxes: the front door and the team workers, on NixOS EC2";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  };

  outputs =
    { nixpkgs, ... }:
    {
      nixosConfigurations = {
        arbiter = nixpkgs.lib.nixosSystem {
          modules = [
            ./common.nix
            ./arbiter.nix
          ];
        };
        worker = nixpkgs.lib.nixosSystem {
          modules = [
            ./common.nix
            ./worker.nix
          ];
        };
      };
    };
}
