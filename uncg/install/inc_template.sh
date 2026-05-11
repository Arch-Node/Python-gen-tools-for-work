#!/bin/bash
# The University of North Carolina at Greensboro
# -----------------------------------------------
# File:     inc_template.sh
# Purpose:  Template installer script for UNCG Banner deployments.
#           Called by the Python repoprep library via:
#             bash -x install/<inc>.sh
#           All output (stdout + stderr) is captured and logged by the
#           Python caller -- no manual log setup is needed here.
#
# Sections:
#   1  - Job Variables
#   2  - Set TNS_ADMIN
#   3  - OS Manipulation
#   4  - SQL and PL/SQL
#   5  - ProC
#   6  - Java
#   7  - Perl
#   8  - Cobol
#   9  - Banner Configuration
#   10 - Job Retirement
#   11 - Build Complete / Email Notification
#
# Audit Trail
# Banner UNCG
# Ver   Date       Dev Comment
# ----- ---------- --- -------------------------------------------------------
# 1.0   2025-01-01 --- Initial template
# -----------------------------------------------------------------------

set -euo pipefail

# Abort handler -- emails developer and prints ABORTED banner to stderr
abort() {
    echo >&2 '*** ABORTED ***'
    if [[ "${DEVELOPER:-none}" != "none" ]]; then
        mailx -s "Build for $INCIDENT ABORTED on $ORACLE_SID" \
              -r "no_reply@uncg.edu" \
              "$DEVELOPER $TRACKING_EMAIL"
    fi
}
trap abort ERR

##############################################################################
# Section 1 - Job Variables
# Change these for every build.  Leave unused optional fields as "none".
##############################################################################

TRACKING_EMAIL="its-banner-deployments@uncg.edu"
DEVELOPER="developer@uncg.edu"   # email(s) separated by spaces; use "none" to skip
STAKEHOLDERS="none"               # additional recipient(s) or "none"
CLIENT="none"                     # client email(s) for test-ready notice or "none"

JOBNAME="job_name_here"
INCIDENT="inc0000000"

echo "**************************************************"
echo "Section 1 - Job Variables"
echo "  INCIDENT    = $INCIDENT"
echo "  JOBNAME     = $JOBNAME"
echo "  ORACLE_SID  = ${ORACLE_SID:-<not set>}"
echo "  DEVELOPER   = $DEVELOPER"
echo "  STAKEHOLDERS= $STAKEHOLDERS"
echo "  CLIENT      = $CLIENT"
echo "**************************************************"

##############################################################################
# Section 2 - Set TNS_ADMIN
# Points to the Oracle Wallet so credentials are not embedded in scripts.
##############################################################################

echo "Section 2 - Setting TNS_ADMIN"
TNS_ADMIN=/banvol/wallet/deploy
export TNS_ADMIN
echo "  TNS_ADMIN = $TNS_ADMIN"

##############################################################################
# Section 3 - OS Manipulation
# Set file permissions and create links.  Comment out unused lines.
##############################################################################

echo "Section 3 - OS Manipulation"
# ln -f "$BANNER_HOME/uncg/uncgmgr/misc/$JOBNAME.shl" "$BANNER_LINKS"
echo "  (no OS changes required)"

##############################################################################
# Section 4 - SQL and PL/SQL
# Add sqlplus calls as needed.  Unused calls should be commented out.
##############################################################################

echo "Section 4 - SQL and PL/SQL"
# sqlplus -l '[UNCGMGR]'/@deploy << EOF
#   whenever sqlerror exit 1;
#   @$BANNER_HOME/uncg/uncgmgr/dbprocs/${JOBNAME}_spec.sql
#   @$BANNER_HOME/uncg/uncgmgr/dbprocs/${JOBNAME}_body.sql
#   exit;
# EOF
echo "  (no SQL changes required)"

##############################################################################
# Section 5 - ProC  (comment out if not used)
##############################################################################

echo "Section 5 - ProC"
echo "  (not used)"

##############################################################################
# Section 6 - Java  (comment out if not used)
##############################################################################

echo "Section 6 - Java"
echo "  (not used)"

##############################################################################
# Section 7 - Perl  (comment out if not used)
##############################################################################

echo "Section 7 - Perl"
echo "  (not used)"

##############################################################################
# Section 8 - Cobol  (comment out if not used)
##############################################################################

echo "Section 8 - Cobol"
echo "  (not used)"

##############################################################################
# Section 9 - Banner Configuration  (comment out if not used)
##############################################################################

echo "Section 9 - Banner Configuration"
echo "  (not used)"

##############################################################################
# Section 10 - Job Retirement  (comment out if not used)
##############################################################################

echo "Section 10 - Job Retirement"
echo "  (not used)"

##############################################################################
# Section 11 - Build Complete / Email Notification
# Elapsed time uses $SECONDS -- set automatically by bash at script start.
##############################################################################

echo "**************************************************"
echo "Section 11 - Build complete for $JOBNAME"
echo "  Elapsed: ${SECONDS}s"
echo "**************************************************"

if [[ "${DEVELOPER:-none}" != "none" ]]; then
    RECIPIENTS="$DEVELOPER $TRACKING_EMAIL"
    [[ "${STAKEHOLDERS:-none}" != "none" ]] && RECIPIENTS="$RECIPIENTS $STAKEHOLDERS"
    mailx -s "Build for $INCIDENT complete on $ORACLE_SID" \
          -r "no_reply@uncg.edu" \
          "$RECIPIENTS"
fi

if [[ "${CLIENT:-none}" != "none" ]] \
   && [[ "${ORACLE_SID:-}" != "ugdev8" ]] \
   && [[ "${ORACLE_SID:-}" != "ugval7" ]]; then
    mailx -s "$INCIDENT applied to $ORACLE_SID" \
          -r "no_reply@uncg.edu" \
          "$CLIENT" \
          <<< "Incident $INCIDENT has been applied to $ORACLE_SID and is ready for testing.

This is an automatically generated message. Do not reply."
fi

trap - ERR
echo >&2 '*** DONE ***'
