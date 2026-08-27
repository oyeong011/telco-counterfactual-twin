#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_GCLOUD_LOG"
policy_state="$FAKE_GCLOUD_LOG-policy"
provider_state="$FAKE_GCLOUD_LOG-provider"
deny_provider_state="$FAKE_GCLOUD_LOG-deny-provider"
topic_state="$FAKE_GCLOUD_LOG-topic"
budget_state="$FAKE_GCLOUD_LOG-budget"

print_target_provider() {
  printf '%s\n' '{"oidc":{"issuerUri":"https://token.actions.githubusercontent.com"},"attributeMapping":{"google.subject":"assertion.sub","attribute.repository":"assertion.repository","attribute.repository_owner_id":"assertion.repository_owner_id"},"attributeCondition":"assertion.repository_owner_id=='\''12345678'\'' && assertion.repository in ['\''oyeong011/telco-counterfactual-twin'\'','\''oyeong011/mcp-evidence-plane'\'']"}'
}

print_deny_provider() {
  provider_id="$(cat "$deny_provider_state")"
  prefix='[{"name":"projects/987654321/locations/global/workloadIdentityPools/github-actions/providers/'
  suffix='","oidc":{"issuerUri":"https://token.actions.githubusercontent.com"},"attributeMapping":{"google.subject":"assertion.sub","attribute.repository":"assertion.repository","attribute.repository_owner_id":"assertion.repository_owner_id"},"attributeCondition":"assertion.repository=='\''oyeong011/nonmatching-preflight'\''"}]'
  printf '%s%s%s\n' "$prefix" "$provider_id" "$suffix"
}

print_policy() {
  if test ! -s "$policy_state"; then
    printf '%s\n' '{"bindings":[]}'
    return
  fi
  printf '%s' '{"bindings":[{"role":"roles/iam.workloadIdentityUser","members":['
  separator=''
  while IFS= read -r member; do
    printf '%s"%s"' "$separator" "$member"
    separator=','
  done < "$policy_state"
  printf '%s\n' ']}]}'
}

print_budget() {
  if test "${FAKE_WRONG_SCHEMA:-0}" = 1; then schema=2.0; else schema=1.0; fi
  display="$(cat "$budget_state")"
  prefix='{"name":"billingAccounts/ABC/budgets/123","displayName":"'
  middle='","budgetFilter":{"projects":["projects/987654321"]},"notificationsRule":{"schemaVersion":"'
  suffix='","pubsubTopic":"projects/example-project/topics/'
  printf '%s%s%s%s%s%s%s' "$prefix" "$display" "$middle" "$schema" "$suffix" "$display" '"}}'
}

case "$*" in
  *"auth list"*) printf '%s\n' 'test-account@example.invalid' ;;
  *"projects describe"*) printf '%s\n' '987654321' ;;
  *"service-accounts describe"*) test -f "$FAKE_SA_STATE"; exit $? ;;
  *"service-accounts list"*)
    if test -f "$FAKE_SA_STATE"; then
      printf '%s\n' '[{"name":"projects/example-project/serviceAccounts/skt-portfolio-deployer@example-project.iam.gserviceaccount.com","email":"skt-portfolio-deployer@example-project.iam.gserviceaccount.com","displayName":"SKT Portfolio Deployer"}]'
    else
      printf '%s\n' '[]'
    fi
    ;;
  *"service-accounts get-iam-policy"*)
    if test -f "$FAKE_SA_STATE"; then print_policy; else exit 1; fi
    ;;
  *"service-accounts create"*) : > "$FAKE_SA_STATE" ;;
  *"service-accounts delete"*) rm "$FAKE_SA_STATE" ;;
  *"service-accounts add-iam-policy-binding"*)
    for arg in "$@"; do
      case "$arg" in --member=*) printf '%s\n' "${arg#--member=}" >> "$policy_state" ;; esac
    done
    ;;
  *"service-accounts remove-iam-policy-binding"*) : > "$policy_state" ;;
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
      printf '%s\n' '{"oidc":{"issuerUri":"x"},"attributeMapping":{},"attributeCondition":"false"}'
    fi
    ;;
  *"providers create-oidc"*)
    provider_id="$5"
    case "$provider_id" in
      github-oidc-deny-*) printf '%s' "$provider_id" > "$deny_provider_state" ;;
      *) : > "$provider_state" ;;
    esac
    ;;
  *"providers update-oidc"*)
    case "$*" in
      *"--issuer-uri=x"*) rm "$provider_state" ;;
      *) : > "$provider_state" ;;
    esac
    ;;
  *"providers delete"*) rm "$deny_provider_state" ;;
  *"pubsub topics list"*)
    if test -f "$topic_state"; then
      topic="$(cat "$topic_state")"
      printf '[{"name":"projects/example-project/topics/%s"}]\n' "$topic"
    else
      printf '%s\n' '[]'
    fi
    ;;
  *"pubsub topics create"*) printf '%s' "$4" > "$topic_state" ;;
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
    if test "${FAKE_FAIL_BUDGET:-0}" = 1; then exit 1; fi
    for arg in "$@"; do
      case "$arg" in --display-name=*) printf '%s' "${arg#--display-name=}" > "$budget_state" ;; esac
    done
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
