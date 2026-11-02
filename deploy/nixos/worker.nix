# A worker box: the box agent and the team checkouts it works in. Nothing on
# it needs a person. Claude runs on Bedrock through the instance's IAM role,
# or on the Claude API with a key the box reads from Secrets Manager.
# GitHub access comes from the arbiter as hour-long tokens for its teams'
# repositories; the box never sees the GitHub App's key.
{
  lib,
  pkgs,
  box,
  ...
}:

let
  home = "/home/${box.username}";
  arbiterCheckout = "/var/lib/arbiter-box/arbiter";
  warlockCheckout = "/var/lib/arbiter-box/warlock";

  # An API key from Secrets Manager replaces Bedrock when Terraform sets one.
  useApiKey = (box.anthropic_api_key_secret_arn or null) != null;

  # Flags for every headless Claude run. The worker plugin does the work; the
  # warlock plugin's hooks keep it inside the ticket's scope.
  claudeArgs = lib.concatStringsSep " " (
    [
      "--plugin-dir ${arbiterCheckout}/plugins/worker"
      "--plugin-dir ${warlockCheckout}"
      "--permission-mode acceptEdits"
      "--allowedTools"
    ]
    ++ map lib.escapeShellArg (
      [
        "Read"
        "Grep"
        "Glob"
        "Agent"
        # Test plans often start with `cd dir && ...`. Claude Code checks each
        # part of a compound command, so `cd` needs its own rule.
        "Bash(cd:*)"
        "Bash(git:*)"
        "Bash(gh:*)"
        "Bash(python3:*)"
      ]
      ++ box.allowed_tools
    )
  );

  # A headless run sees only this PATH.
  claudeTools = lib.makeBinPath [
    pkgs.awscli2
    pkgs.claude-code
    pkgs.coreutils
    pkgs.curl
    pkgs.gh
    pkgs.git
    pkgs.gnugrep
    pkgs.jq
    pkgs.python3
  ];

  # Clones arbiter and warlock, which are public, then starts the box agent.
  # The agent gets a GitHub token from the arbiter, logs gh in with it (gh is
  # git's credential helper), clones each team's repository, and refreshes the
  # token every 40 minutes.
  boxStart = pkgs.writeShellScript "arbiter-box-start" ''
    set -euo pipefail
    export PATH=${claudeTools}:$PATH

    clone() { [ -d "$2/.git" ] || git clone --branch "$3" "$1" "$2"; }
    clone '${box.arbiter_repo}' ${arbiterCheckout} '${box.arbiter_ref}'
    clone 'https://github.com/Genetic-Pottery/warlock.git' ${warlockCheckout} '${box.warlock_ref}'
    ${lib.optionalString useApiKey ''
      ANTHROPIC_API_KEY=$(aws secretsmanager get-secret-value --region '${box.aws_region}' \
        --secret-id '${box.anthropic_api_key_secret_arn}' --query SecretString --output text)
      export ANTHROPIC_API_KEY
    ''}

    # Each team works in its own clone of its repository.
    teams=(${
      lib.escapeShellArgs (
        lib.concatLists (
          lib.mapAttrsToList (team: repo: [
            "--team"
            "${team}=${home}/work/${team}"
            "--repo"
            "${team}=${repo}"
          ]) box.teams
        )
      )
    })

    # The arbiter reaches this box at its private address.
    imds=http://169.254.169.254/latest
    imds_token=$(curl -fsS -X PUT "$imds/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
    private_ip=$(curl -fsS -H "X-aws-ec2-metadata-token: $imds_token" "$imds/meta-data/local-ipv4")

    cd ${arbiterCheckout}
    exec python3 -m arbiter box \
      --arbiter '${box.arbiter_url}' \
      --host 0.0.0.0 --port ${toString box.box_port} \
      --advertise "http://$private_ip:${toString box.box_port}" \
      --state-dir /var/lib/arbiter-box/state \
      --warlock-cli ${warlockCheckout}/scripts/warlock.py \
      --claude-args ${lib.escapeShellArg claudeArgs} \
      "''${teams[@]}"
  '';

  claudeEnv = {
    HOME = home;
    AWS_REGION = box.aws_region;
  }
  // lib.optionalAttrs (!useApiKey) { CLAUDE_CODE_USE_BEDROCK = "1"; }
  // lib.optionalAttrs (box.claude_model != null) { ANTHROPIC_MODEL = box.claude_model; };
in
{
  networking.firewall.allowedTCPPorts = [ box.box_port ];

  systemd.tmpfiles.rules = [
    "d ${home}/work 0755 ${box.username} users -"
    "d /var/lib/arbiter-box 0755 ${box.username} users -"
  ];

  systemd.services.arbiter-box = {
    description = "arbiter box agent";
    wantedBy = [ "multi-user.target" ];
    wants = [ "network-online.target" ];
    after = [ "network-online.target" ];
    path = [
      "/run/wrappers"
      "/run/current-system/sw"
    ];
    environment = claudeEnv;
    serviceConfig = {
      User = box.username;
      ExecStart = boxStart;
      Restart = "always";
      RestartSec = 30;
    };
  };
}
