# A worker box: the box agent and the team checkouts it works in. Nothing on
# it needs a person. Claude runs on Bedrock through the instance's IAM role,
# and GitHub access comes from a GitHub App whose key is in Secrets Manager.
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
    pkgs.openssl
    pkgs.python3
  ];

  # Trades the GitHub App's private key for an installation token, which lasts
  # an hour, and logs gh in with it. gh is also git's credential helper.
  githubToken = pkgs.writeShellScript "github-token" ''
    set -euo pipefail
    export PATH=${claudeTools}:$PATH
    secret=$(aws secretsmanager get-secret-value --region '${box.aws_region}' \
      --secret-id '${box.github_app_secret_arn}' --query SecretString --output text)
    app_id=$(jq -r .app_id <<<"$secret")
    installation_id=$(jq -r .installation_id <<<"$secret")
    key=$(mktemp)
    trap 'rm -f "$key"' EXIT
    jq -r .private_key <<<"$secret" > "$key"

    b64url() { openssl base64 -A | tr '+/' '-_' | tr -d '='; }
    now=$(date +%s)
    header=$(printf '{"alg":"RS256","typ":"JWT"}' | b64url)
    payload=$(printf '{"iat":%d,"exp":%d,"iss":"%s"}' $((now - 60)) $((now + 540)) "$app_id" | b64url)
    signature=$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -sign "$key" | b64url)

    token=$(curl -fsS -X POST \
      -H "Authorization: Bearer $header.$payload.$signature" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/app/installations/$installation_id/access_tokens" | jq -r .token)
    gh auth login --with-token <<<"$token"
  '';

  # Clones what the box agent needs, then starts it with this box's teams.
  boxStart = pkgs.writeShellScript "arbiter-box-start" ''
    set -euo pipefail
    export PATH=${claudeTools}:$PATH
    ${githubToken}

    clone() { [ -d "$2/.git" ] || git clone --branch "$3" "$1" "$2"; }
    clone '${box.arbiter_repo}' ${arbiterCheckout} '${box.arbiter_ref}'
    clone 'https://github.com/Genetic-Pottery/warlock.git' ${warlockCheckout} '${box.warlock_ref}'

    teams=()
    for team in ${lib.escapeShellArgs box.teams}; do
      dir='${home}/work/'"$team"
      [ -d "$dir/.git" ] || gh repo clone '${box.project_repo}' "$dir"
      teams+=(--team "$team=$dir")
    done

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
    CLAUDE_CODE_USE_BEDROCK = "1";
    AWS_REGION = box.aws_region;
  }
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

  # An installation token lasts an hour. Refresh it well before then; runs
  # already started pick up the new token through gh.
  systemd.services.github-token = {
    description = "Refresh the GitHub App token";
    environment = claudeEnv;
    serviceConfig = {
      Type = "oneshot";
      User = box.username;
      ExecStart = githubToken;
    };
  };
  systemd.timers.github-token = {
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnBootSec = "40min";
      OnUnitActiveSec = "40min";
    };
  };
}
