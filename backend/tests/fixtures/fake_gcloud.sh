#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_GCLOUD_LOG"
policy_state="$FAKE_GCLOUD_LOG-policy"
provider_state="$FAKE_GCLOUD_LOG-provider"
deny_provider_state="$FAKE_GCLOUD_LOG-deny-provider"
topic_state="$FAKE_GCLOUD_LOG-topic"
budget_state="$FAKE_GCLOUD_LOG-budget"

print_target_provider() {
  description="$(cat "$provider_state")"
  prefix='{"name":"projects/987654321/locations/global/workloadIdentityPools/github-actions/providers/github-oidc","oidc":{"issuerUri":"https://token.actions.githubusercontent.com"},"attributeMapping":{"google.subject":"assertion.sub","attribute.repository":"assertion.repository","attribute.repository_owner_id":"assertion.repository_owner_id"},"attributeCondition":"assertion.repository_owner_id=='\''12345678'\'' && assertion.repository in ['\''oyeong011/telco-counterfactual-twin'\'','\''oyeong011/mcp-evidence-plane'\'']","description":"'
  printf '%s%s%s\n' "$prefix" "$description" '"}'
}

print_deny_provider() {
  provider_id="$(sed -n '1p' "$deny_provider_state")"
  description="$(sed -n '2p' "$deny_provider_state")"
  prefix='[{"name":"projects/987654321/locations/global/workloadIdentityPools/github-actions/providers/'
  middle='","oidc":{"issuerUri":"https://token.actions.githubusercontent.com"},"attributeMapping":{"google.subject":"assertion.sub","attribute.repository":"assertion.repository","attribute.repository_owner_id":"assertion.repository_owner_id"},"attributeCondition":"assertion.repository=='\''oyeong011/nonmatching-preflight'\''","description":"'
  printf '%s%s%s%s%s\n' "$prefix" "$provider_id" "$middle" "$description" '"}]'
}

print_policy() {
  if test ! -s "$policy_state"; then
    printf '%s\n' '{"bindings":[]}'
    return
  fi
  printf '%s' '{"bindings":['
  separator=''
  tab="$(printf '\t')"
  while IFS="$tab" read -r member marker; do
    prefix='{"role":"roles/iam.workloadIdentityUser","members":["'
    middle='"],"condition":{"expression":"true","title":"'
    printf '%s%s%s%s%s%s%s' "$separator" "$prefix" "$member" "$middle" "$marker" '","description":"' "$marker"
    printf '%s' '"}}'
    separator=','
  done < "$policy_state"
  printf '%s\n' ']}'
}

print_budget() {
  if test "${FAKE_WRONG_SCHEMA:-0}" = 1; then schema=2.0; else schema=1.0; fi
  display="$(sed -n '1p' "$budget_state")"
  topic="$(sed -n '2p' "$budget_state")"
  prefix='{"name":"billingAccounts/ABC/budgets/123","displayName":"'
  middle='","budgetFilter":{"projects":["projects/987654321"]},"notificationsRule":{"schemaVersion":"'
  suffix='","pubsubTopic":"projects/example-project/topics/'
  printf '%s%s%s%s%s%s%s' "$prefix" "$display" "$middle" "$schema" "$suffix" "$topic" '"}}'
}

case "$*" in
  *"auth list"*) printf '%s\n' 'test-account@example.invalid' ;;
  *"projects describe"*) printf '%s\n' '987654321' ;;
  *"service-accounts describe"*) test -f "$FAKE_SA_STATE"; exit $? ;;
  *"service-accounts list"*)
    if test -f "$FAKE_SA_STATE"; then
      description="$(cat "$FAKE_SA_STATE")"
      prefix='[{"name":"projects/example-project/serviceAccounts/skt-portfolio-deployer@example-project.iam.gserviceaccount.com","uniqueId":"123456789012345678901","email":"skt-portfolio-deployer@example-project.iam.gserviceaccount.com","displayName":"SKT Portfolio Deployer","description":"'
      printf '%s%s%s\n' "$prefix" "$description" '"}]'
    else
      printf '%s\n' '[]'
    fi
    ;;
  *"service-accounts get-iam-policy"*)
    if test -f "$FAKE_SA_STATE"; then print_policy; else exit 1; fi
    ;;
  *"service-accounts create"*)
    for arg in "$@"; do
      case "$arg" in --description=*) printf '%s' "${arg#--description=}" > "$FAKE_SA_STATE" ;; esac
    done
    ;;
  *"service-accounts delete"*) rm "$FAKE_SA_STATE" ;;
  *"service-accounts add-iam-policy-binding"*)
    member=''
    marker=''
    for arg in "$@"; do
      case "$arg" in
        --member=*) member="${arg#--member=}" ;;
        --condition=*)
          condition="${arg#--condition=}"
          marker="$(printf '%s' "$condition" | sed 's/^.*title=//;s/,description=.*$//')"
          ;;
      esac
    done
    printf '%s\t%s\n' "$member" "$marker" >> "$policy_state"
    ;;
  *"service-accounts remove-iam-policy-binding"*)
    member=''
    marker=''
    for arg in "$@"; do
      case "$arg" in
        --member=*) member="${arg#--member=}" ;;
        --condition=*)
          condition="${arg#--condition=}"
          marker="$(printf '%s' "$condition" | sed 's/^.*title=//;s/,description=.*$//')"
          ;;
      esac
    done
    if test -f "$policy_state"; then
      awk -F '\t' -v member="$member" -v marker="$marker" '!(($1 == member) && ($2 == marker))' "$policy_state" > "$policy_state-next"
      mv "$policy_state-next" "$policy_state"
    fi
    ;;
  *"service-accounts set-iam-policy"*)
    : > "$policy_state"
    grep -o 'principalSet[^" ]*' "$5" > "$policy_state"
    ;;
  *"workload-identity-pools describe"*)
    printf '%s\n' '{"name":"projects/987654321/locations/global/workloadIdentityPools/github-actions","displayName":"GitHub Actions"}'
    ;;
  *"providers list"*)
    if test -f "$deny_provider_state"; then print_deny_provider; else printf '%s\n' '[]'; fi
    ;;
  *"providers describe github-oidc "*|*"providers describe github-oidc --"*)
    if test -f "$provider_state"; then
      print_target_provider
    else
      printf '%s\n' '{"name":"projects/987654321/locations/global/workloadIdentityPools/github-actions/providers/github-oidc","oidc":{"issuerUri":"x"},"attributeMapping":{},"attributeCondition":"false","description":"old-provider"}'
    fi
    ;;
  *"providers create-oidc"*)
    provider_id="$5"
    description=''
    for arg in "$@"; do
      case "$arg" in --description=*) description="${arg#--description=}" ;; esac
    done
    case "$provider_id" in
      github-oidc-deny-*) printf '%s\n%s' "$provider_id" "$description" > "$deny_provider_state" ;;
      *) printf '%s' "$description" > "$provider_state" ;;
    esac
    ;;
  *"providers update-oidc"*)
    case "$*" in
      *"--issuer-uri=x"*) rm "$provider_state" ;;
      *)
        for arg in "$@"; do
          case "$arg" in --description=*) printf '%s' "${arg#--description=}" > "$provider_state" ;; esac
        done
        ;;
    esac
    ;;
  *"providers delete"*) rm "$deny_provider_state" ;;
  *"pubsub topics list"*)
    if test -f "$topic_state"; then
      topic="$(sed -n '1p' "$topic_state")"
      fingerprint="$(sed -n '2p' "$topic_state")"
      prefix='[{"name":"projects/example-project/topics/'
      middle='","labels":{"managed-by":"telco-twin-preflight","operation-fingerprint":"'
      printf '%s%s%s%s%s\n' "$prefix" "$topic" "$middle" "$fingerprint" '"}}]'
    else
      printf '%s\n' '[]'
    fi
    ;;
  *"pubsub topics create"*)
    fingerprint=''
    for arg in "$@"; do
      case "$arg" in
        --labels=*) fingerprint="$(printf '%s' "${arg#--labels=}" | sed 's/^.*operation-fingerprint=//')" ;;
      esac
    done
    printf '%s\n%s' "$4" "$fingerprint" > "$topic_state"
    ;;
  *"pubsub topics delete"*) rm "$topic_state" ;;
  *"billing budgets list"*)
    if test -f "$budget_state"; then
      printf '['
      print_budget
      printf ']\n'
    else
      printf '%s\n' '[]'
    fi
    ;;
  *"billing budgets create"*)
    display=''
    topic=''
    for arg in "$@"; do
      case "$arg" in
        --display-name=*) display="${arg#--display-name=}" ;;
        --notifications-rule-pubsub-topic=*)
          topic="${arg#--notifications-rule-pubsub-topic=projects/example-project/topics/}"
          ;;
      esac
    done
    printf '%s\n%s' "$display" "$topic" > "$budget_state"
    if test "${FAKE_FAIL_BUDGET:-0}" = 1; then exit 1; fi
    printf '%s\n' 'billingAccounts/ABC/budgets/123'
    ;;
  *"billing budgets describe"*) print_budget; printf '\n' ;;
  *"billing budgets delete"*) rm "$budget_state" ;;
  *"pubsub topics get-iam-policy"*)
    if test "${FAKE_WRONG_PUBLISHER:-0}" = 1; then
      member=wrong@example.invalid
    else
      member=billing-budget-alert@system.gserviceaccount.com
    fi
    prefix='{"bindings":[{"role":"roles/pubsub.publisher","members":["serviceAccount:'
    printf '%s%s%s\n' "$prefix" "$member" '"]}]}'
    ;;
esac
exit 0
