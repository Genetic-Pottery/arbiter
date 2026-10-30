# What every arbiter box shares: the image, the user, Nix, swap, and the tools
# Claude's skills drive. Terraform writes per-box values to box.json.
{
  lib,
  pkgs,
  modulesPath,
  ...
}:

let
  box = builtins.fromJSON (builtins.readFile ./box.json);
in
{
  imports = [ "${modulesPath}/virtualisation/amazon-image.nix" ];

  # The role modules read box.json through this argument.
  _module.args.box = box;

  nixpkgs.hostPlatform = box.host_platform;
  system.stateVersion = box.state_version;
  networking.hostName = box.hostname;

  # User-data already did its job on first boot; don't run it again.
  virtualisation.amazon-init.enable = false;

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];
  nix.gc = {
    automatic = true;
    dates = "weekly";
    options = "--delete-older-than 14d";
  };

  nixpkgs.config.allowUnfreePredicate = pkg: builtins.elem (lib.getName pkg) [ "claude-code" ];

  # Headroom for long Claude Code sessions and their subagents.
  swapDevices = [
    {
      device = "/var/lib/swapfile";
      size = 4096;
    }
  ];

  users.users.${box.username} = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];
  };
  security.sudo.wheelNeedsPassword = false;

  # No SSH server. The arbiter box is reached over Tailscale SSH; workers are
  # reached with AWS Systems Manager Session Manager.
  services.openssh.enable = lib.mkForce false;
  services.amazon-ssm-agent.enable = true;

  environment.systemPackages = with pkgs; [
    awscli2
    claude-code
    curl
    fd
    gh
    git
    jq
    python3
    ripgrep
  ];

  programs.git = {
    enable = true;
    config = {
      user = {
        name = box.git_user_name;
        email = box.git_user_email;
      };
      init.defaultBranch = "main";
      pull.rebase = false;
      credential."https://github.com".helper = "!${pkgs.gh}/bin/gh auth git-credential";
    };
  };
}
