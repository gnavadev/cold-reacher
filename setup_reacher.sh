#!/usr/bin/env bash
# =============================================================================
# setup_reacher.sh
# Sets up Reacher (open-source email verifier) on Oracle Cloud Free Tier
# or any Oracle Linux / RHEL / Fedora server.
#
# Run as root (or with sudo):
#   chmod +x setup_reacher.sh && sudo ./setup_reacher.sh
# =============================================================================
set -euo pipefail

REACHER_PORT=8080
REACHER_IMAGE="reacherhq/backend:latest"
CONTAINER_NAME="reacher"

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }

# ── Detect distro ────────────────────────────────────────────────────────────
if   command -v dnf  &>/dev/null; then PKG="dnf";  DISTRO="rhel"
elif command -v apt  &>/dev/null; then PKG="apt";  DISTRO="debian"
else echo -e "${RED}Unsupported distro${NC}"; exit 1; fi

info "Detected package manager: $PKG"

# ── 1. Install Docker ─────────────────────────────────────────────────────────
info "Installing Docker..."
if command -v docker &>/dev/null; then
    success "Docker already installed: $(docker --version)"
else
    if [[ "$DISTRO" == "rhel" ]]; then
        dnf -y install dnf-plugins-core
        dnf config-manager --add-repo \
            https://download.docker.com/linux/rhel/docker-ce.repo 2>/dev/null \
            || dnf config-manager --add-repo \
               https://download.docker.com/linux/centos/docker-ce.repo
        dnf -y install docker-ce docker-ce-cli containerd.io docker-compose-plugin
    else
        apt-get update -qq
        apt-get install -y -qq ca-certificates curl gnupg
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
            | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
        chmod a+r /etc/apt/keyrings/docker.gpg
        echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
            > /etc/apt/sources.list.d/docker.list
        apt-get update -qq
        apt-get install -y -qq docker-ce docker-ce-cli containerd.io
    fi
    systemctl enable --now docker
    success "Docker installed."
fi

# ── 2. Open firewall port ─────────────────────────────────────────────────────
info "Opening port $REACHER_PORT in firewall..."

# iptables (Oracle Cloud uses this by default — firewalld is NOT active)
if iptables -L INPUT -n | grep -q "dpt:$REACHER_PORT" 2>/dev/null; then
    success "iptables rule already present."
else
    iptables  -I INPUT  -p tcp --dport $REACHER_PORT -j ACCEPT
    ip6tables -I INPUT  -p tcp --dport $REACHER_PORT -j ACCEPT

    # Persist across reboots
    if [[ "$DISTRO" == "rhel" ]]; then
        dnf -y install iptables-services 2>/dev/null || true
        service iptables  save 2>/dev/null || iptables-save  > /etc/sysconfig/iptables
        service ip6tables save 2>/dev/null || ip6tables-save > /etc/sysconfig/ip6tables
    else
        apt-get install -y -qq iptables-persistent
        netfilter-persistent save
    fi
    success "iptables rule added and persisted."
fi

# Also open via firewalld if it happens to be running
if systemctl is-active --quiet firewalld 2>/dev/null; then
    firewall-cmd --permanent --add-port=${REACHER_PORT}/tcp
    firewall-cmd --reload
    success "firewalld rule added."
fi

# ── 3. Pull & run Reacher ─────────────────────────────────────────────────────
info "Pulling Reacher image ($REACHER_IMAGE)..."
docker pull "$REACHER_IMAGE"

# Stop old container if it exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    warn "Stopping existing '$CONTAINER_NAME' container..."
    docker stop  "$CONTAINER_NAME" || true
    docker rm    "$CONTAINER_NAME" || true
fi

info "Starting Reacher on port $REACHER_PORT..."
docker run -d \
    --name          "$CONTAINER_NAME" \
    --restart       unless-stopped \
    -p              "${REACHER_PORT}:8080" \
    "$REACHER_IMAGE"

sleep 2   # give the container a moment to start

# ── 4. Smoke test ─────────────────────────────────────────────────────────────
info "Running smoke test..."
RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST http://localhost:${REACHER_PORT}/v0/check_email \
    -H 'Content-Type: application/json' \
    -d '{"to_email":"test@gmail.com"}' || echo "000")

if [[ "$RESPONSE" == "200" ]]; then
    success "Reacher is responding correctly (HTTP 200)."
else
    warn "Unexpected response code: $RESPONSE"
    warn "Check logs with: docker logs $CONTAINER_NAME"
fi

# ── 5. Print summary ──────────────────────────────────────────────────────────
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || echo "<your-server-ip>")

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Reacher is running!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo ""
echo "  Endpoint:  http://${PUBLIC_IP}:${REACHER_PORT}"
echo ""
echo "  Paste this URL into Cold Reacher:"
echo "  Settings → API Keys → Reacher URL"
echo ""
echo -e "${YELLOW}  ⚠  Oracle Cloud extra step:${NC}"
echo "  You must also open port $REACHER_PORT in the Oracle Cloud"
echo "  VCN Security List (web console), otherwise traffic is"
echo "  blocked before it reaches this machine."
echo ""
echo "  Path:  Oracle Console → Networking → Virtual Cloud"
echo "         Networks → your VCN → Security Lists → Default"
echo "         → Add Ingress Rule:"
echo "           Source CIDR:   <your home IP>/32"
echo "           Protocol:      TCP"
echo "           Destination port: $REACHER_PORT"
echo ""
echo "  Test from your PC:"
echo "  curl -X POST http://${PUBLIC_IP}:${REACHER_PORT}/v0/check_email \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"to_email\":\"test@gmail.com\"}'"
echo ""
