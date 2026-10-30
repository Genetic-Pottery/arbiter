# The front door: the arbiter service, and the Claude session you reach from
# the Claude app through Remote Control. This is the only box with a claude.ai
# login and tracker access, so its setup has a few manual steps.
{
  lib,
  pkgs,
  box,
  ...
}:

let
  home = "/home/${box.username}";
  project = "${home}/Projects/${box.project_name}";

  claudeTools = lib.makeBinPath [
    pkgs.claude-code
    pkgs.gh
    pkgs.git
    pkgs.jq
    pkgs.python3
  ];

  # The arbiter service runs from this checkout of the arbiter repository.
  arbiterCheckout = "/var/lib/arbiter/src";

  # Installs the warlock and arbiter plugins, and clones the project the
  # session works in. Run it once after `gh auth login` and the Claude login.
  arbiterInstall = pkgs.writeShellScriptBin "arbiter-install" ''
    set -euo pipefail
    export PATH=${claudeTools}:$PATH
    add() {
      if ! claude plugin marketplace list --json | jq -e --arg n "$1" 'any(.[]; .name == $n)' >/dev/null; then
        claude plugin marketplace add "$2"
      fi
    }
    add warlock 'https://github.com/Genetic-Pottery/warlock.git#${box.warlock_ref}'
    add arbiter '${box.arbiter_repo}#${box.arbiter_ref}'
    for p in warlock@warlock arbiter@arbiter; do
      if ! claude plugin list --json | jq -e --arg p "$p" 'any(.[]; .id == $p)' >/dev/null; then
        claude plugin install "$p"
      fi
    done
    if [ ! -d '${project}/.git' ]; then
      gh repo clone '${box.project_repo}' '${project}'
    fi
    echo "Plugins installed and ${box.project_name} cloned. Next, run 'remote-control-enable'."
  '';

  remoteControlMarker = "${home}/.local/state/arbiter/remote-control";

  remoteControlEnable = pkgs.writeShellScriptBin "remote-control-enable" ''
    set -euo pipefail
    export PATH=${claudeTools}:$PATH
    cd '${project}'
    echo "Starting Remote Control in ${project}. Answer its prompts, check that"
    echo "this box shows up in the Claude app, then press Ctrl-C."
    trap : INT
    claude remote-control || true
    trap - INT
    mkdir -p "$(dirname ${remoteControlMarker})"
    touch ${remoteControlMarker}
    sudo systemctl restart remote-control
    echo "Remote Control is running. In the Claude app, open a session and run /arbiter:watch."
  '';

  boxStatus = pkgs.writeShellScriptBin "box-status" ''
    ok()   { printf '  [x] %s\n' "$1"; }
    todo() { printf '  [ ] %s\n' "$1"; }
    export PATH=${claudeTools}:$PATH
    echo
    echo "arbiter box"
    if systemctl is-active --quiet arbiter; then ok "arbiter service: running"; else todo "arbiter service: see 'journalctl -u arbiter'"; fi
    if gh auth status >/dev/null 2>&1; then ok "GitHub: logged in"; else todo "GitHub: run 'gh auth login'"; fi
    if [ -s "$HOME/.claude/.credentials.json" ]; then ok "Claude: logged in"; else todo "Claude: run 'claude' and log in"; fi
    if claude plugin list --json 2>/dev/null | jq -e 'any(.[]; .id == "arbiter@arbiter")' >/dev/null; then ok "plugins: installed"; else todo "plugins: run 'arbiter-install'"; fi
    if systemctl is-active --quiet remote-control; then ok "Remote Control: running"; else todo "Remote Control: run 'remote-control-enable'"; fi
    echo "  Trackers: in claude, run '/mcp' and sign in to Linear or Jira"
    echo "  Teams:    python3 -m arbiter teams  (from ${arbiterCheckout})"
    echo
  '';
in
{
  # You reach this box over Tailscale SSH, with your tailnet identity.
  services.tailscale = {
    enable = true;
    authKeyFile = "/var/lib/tailscale-authkey";
    extraUpFlags = [ "--ssh" ];
  };

  networking.firewall.allowedTCPPorts = [ box.arbiter_port ];

  systemd.tmpfiles.rules = [ "d ${home}/Projects 0755 ${box.username} users -" ];

  environment.systemPackages = [
    arbiterInstall
    remoteControlEnable
    boxStatus
  ];

  programs.bash.interactiveShellInit = ''
    if [[ -n "$SSH_CONNECTION" && -z "$TMUX" ]]; then
      box-status
    fi
  '';

  # The registry and event log. Boxes reach it on the private network; the
  # security group admits only worker boxes.
  systemd.services.arbiter = {
    description = "arbiter service";
    wantedBy = [ "multi-user.target" ];
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    path = [ pkgs.git ];
    serviceConfig = {
      User = box.username;
      StateDirectory = "arbiter";
      ExecStartPre = pkgs.writeShellScript "arbiter-checkout" ''
        set -eu
        if [ ! -d ${arbiterCheckout}/.git ]; then
          git clone --branch '${box.arbiter_ref}' '${box.arbiter_repo}' ${arbiterCheckout}
        fi
      '';
      WorkingDirectory = arbiterCheckout;
      ExecStart = "${pkgs.python3}/bin/python3 -m arbiter serve --host 0.0.0.0 --port ${toString box.arbiter_port} --events-file /var/lib/arbiter/events.jsonl";
      Restart = "always";
      RestartSec = 5;
    };
  };

  # Sessions from the Claude app start in the project checkout, where
  # .warlock/scopes.toml names the teams.
  systemd.services.remote-control = {
    description = "Claude Code Remote Control server";
    wantedBy = [ "multi-user.target" ];
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    unitConfig = {
      ConditionPathExists = remoteControlMarker;
      StartLimitIntervalSec = 0;
    };
    path = [
      "/run/wrappers"
      "/run/current-system/sw"
    ];
    environment.HOME = home;
    serviceConfig = {
      User = box.username;
      WorkingDirectory = project;
      ExecStart = "${pkgs.claude-code}/bin/claude remote-control --spawn same-dir --capacity 2";
      Restart = "always";
      RestartSec = 30;
    };
  };
}
