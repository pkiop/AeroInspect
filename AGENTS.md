# Agent 작업 가이드

모든 Agent는 작업 시 다음 프로세스를 항상 준수해야 합니다:

1. **Git Worktree 생성**: 별도의 git worktree를 생성하여 격리된 환경에서 작업을 시작합니다.
2. **Draft PR 생성**: 작업 시작 시 Draft 상태의 Pull Request(PR)를 생성합니다.
3. **작업 진행**: 할당된 코드 작성, 수정 등의 작업을 진행합니다.
4. **작업 내역 작성**: 진행된 모든 작업 내역을 Draft PR 본문에 기록합니다.
5. **Review Request**: 작업이 완료되면 Draft 상태를 해제하고 (또는 Ready for Review 상태로 변경하고) 리뷰어에게 Review를 요청합니다.
