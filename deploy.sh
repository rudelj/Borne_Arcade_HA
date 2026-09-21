#!/bin/bash
# ==============================================================================
# Script de déploiement automatique du Kiosk Home Assistant sur Borne d'Arcade Batocera
# Dépôt GitHub : https://github.com/rudelj/Borne_Arcade_HA
# ==============================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================================================${NC}"
echo -e "${BLUE}  Déploiement du Kiosk Home Assistant pour Borne d'Arcade Batocera${NC}"
echo -e "${BLUE}================================================================${NC}"

# 1. Vérification de l'environnement Batocera
if [ ! -d "/userdata/system" ]; then
    echo -e "${RED}[ERREUR] Ce script doit être exécuté sur un système Batocera Linux (/userdata/system introuvable).${NC}"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BATOCERA_SRC="$SCRIPT_DIR/batocera/userdata/system"

if [ ! -d "$BATOCERA_SRC" ]; then
    echo -e "${RED}[ERREUR] Le dossier source $BATOCERA_SRC est introuvable.${NC}"
    exit 1
fi

# 2. Création des répertoires cibles
echo -e "\n${YELLOW}[1/6] Création de l'arborescence dans /userdata/system...${NC}"
mkdir -p /userdata/system/scripts
mkdir -p /userdata/system/configs/ha_kiosk
mkdir -p /userdata/system/configs/ha_kiosk/data
mkdir -p /userdata/system/services
mkdir -p /userdata/system/logs
mkdir -p /userdata/system/lib/gio/modules

# 3. Copie des fichiers exécutables et scripts
echo -e "${YELLOW}[2/6] Installation des scripts et exécutables...${NC}"
cp -f "$BATOCERA_SRC/scripts/ha_kiosk.py" /userdata/system/scripts/
cp -f "$BATOCERA_SRC/scripts/ha_daemon.py" /userdata/system/scripts/
cp -f "$BATOCERA_SRC/services/ha_kiosk" /userdata/system/services/

# 4. Copie de la configuration (ne pas écraser si déjà existante)
echo -e "${YELLOW}[3/6] Configuration du Kiosk...${NC}"
cp -f "$BATOCERA_SRC/configs/ha_kiosk/ha_kiosk.conf.example" /userdata/system/configs/ha_kiosk/

if [ -f "/userdata/system/configs/ha_kiosk/ha_kiosk.conf" ]; then
    echo -e "${GREEN}  -> Fichier de configuration existant conservé (/userdata/system/configs/ha_kiosk/ha_kiosk.conf).${NC}"
    # Backup de sécurité
    cp -f "/userdata/system/configs/ha_kiosk/ha_kiosk.conf" "/userdata/system/configs/ha_kiosk/ha_kiosk.conf.bak_$(date +%Y%m%d_%H%M%S)"
else
    if [ -f "$BATOCERA_SRC/configs/ha_kiosk/ha_kiosk.conf" ]; then
        cp -f "$BATOCERA_SRC/configs/ha_kiosk/ha_kiosk.conf" /userdata/system/configs/ha_kiosk/
        echo -e "${GREEN}  -> Configuration ha_kiosk.conf déployée.${NC}"
    else
        cp -f "$BATOCERA_SRC/configs/ha_kiosk/ha_kiosk.conf.example" /userdata/system/configs/ha_kiosk/ha_kiosk.conf
        echo -e "${YELLOW}  -> Fichier ha_kiosk.conf initialisé à partir du template.${NC}"
    fi
fi

# 5. Configuration de l'autostart Batocera
echo -e "${YELLOW}[4/6] Configuration de l'autostart Batocera (custom.sh)...${NC}"
if [ -f "/userdata/system/custom.sh" ]; then
    if ! grep -q "/userdata/system/services/ha_kiosk" "/userdata/system/custom.sh"; then
        echo -e "\n# Home Assistant Kiosk Daemon\n/userdata/system/services/ha_kiosk start &" >> /userdata/system/custom.sh
    fi
else
    cp -f "$BATOCERA_SRC/custom.sh" /userdata/system/custom.sh
fi

# 6. Droits d'exécution
echo -e "${YELLOW}[5/6] Attribution des permissions d'exécution...${NC}"
chmod +x /userdata/system/scripts/ha_kiosk.py
chmod +x /userdata/system/scripts/ha_daemon.py
chmod +x /userdata/system/services/ha_kiosk
chmod +x /userdata/system/custom.sh

# Déclaration dans batocera.conf pour le gestionnaire de services
if command -v batocera-settings-set &>/dev/null; then
    batocera-settings-set system.services "ha_kiosk"
fi

# Sauvegarde de l'overlay Batocera
echo -e "${YELLOW}[6/6] Sauvegarde de l'overlay Batocera...${NC}"
if command -v batocera-save-overlay &>/dev/null; then
    batocera-save-overlay
fi

# 7. Redémarrage du service
echo -e "\n${GREEN}Lancement du service ha_kiosk...${NC}"
/userdata/system/services/ha_kiosk restart

sleep 2
/userdata/system/services/ha_kiosk status

echo -e "\n${GREEN}================================================================${NC}"
echo -e "${GREEN}  Déploiement terminé avec succès !${NC}"
echo -e "${GREEN}  Le Kiosk Home Assistant est actif sur la borne d'arcade.${NC}"
echo -e "${GREEN}  Fichier de configuration : /userdata/system/configs/ha_kiosk/ha_kiosk.conf${NC}"
echo -e "${GREEN}  Logs du daemon : /userdata/system/logs/ha_daemon.log${NC}"
echo -e "${GREEN}================================================================${NC}"
