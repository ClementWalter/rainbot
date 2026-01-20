There is a PRD.md file in the root of the repository. This file describe the
target product that you need to implement. There is a PLAN.md file in the root
of the repository. This file describe the current status and the plan for the
implementation.

**CRITICAL**: You need to review the plan, don't assume correctness, the plan
may be bad or incomplete.

The source code is in the src directory. The tests are in the tests directory.

1. Analyze the PRD.md, the PLAN.md files and the source code.
2. Identify missing features, bugs, and fix PLAN.md accordingly.
3. If the current git tree is dirty, do an initial commit to isolate previous
   changes from the current feature.
4. Pick the most important feature or bug to implement first, and fix it.
   Scrapping the real paris tennis website and passing the captcha are the most
   important features.
5. Run the tests to ensure the changes are working, add tests for the new
   feature or bug if needed.
6. You need to fix all failing tests, not only your tests.
7. For ui features, use the dev-browser skill.
8. **CRITICAL**: Commit the changes to the repository.
9. Exit

**CRITICAL**: You need to pick only one feature or bug to implement at a time,
don't try to implement multiple features or bugs at once.
