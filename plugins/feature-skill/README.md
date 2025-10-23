# Feature Skill Plugin

Modular skill-based feature development workflow for systematic software engineering.

## Overview

This plugin provides a comprehensive feature development workflow broken into 5 independent, composable skills. Each skill handles a specific phase of development and can be used independently or combined through automatic orchestration.

## Skills Included

### 1. requirements-clarification
**Triggers:** User requests feature with unclear requirements
- Systematically asks clarifying questions
- Builds complete understanding before proceeding
- Confirms requirements with user

### 2. codebase-exploration
**Triggers:** Need to understand existing code structure
- Explores codebase for similar features
- Identifies patterns and conventions
- Maps architecture and integration points

### 3. architecture-design
**Triggers:** Need to design implementation approach
- Generates multiple architecture options
- Presents trade-offs and recommendations
- Lets user choose best approach

### 4. code-implementation
**Triggers:** Ready to write code
- Implements feature following chosen architecture
- Respects codebase conventions
- Handles unexpected situations appropriately

### 5. code-review
**Triggers:** Code needs quality verification
- Reviews for bugs, quality, conventions
- Reports high-confidence issues only
- Applies fixes based on user decision

## Usage

### Full Workflow
```
/feature [feature description]
```

Executes all 5 phases in sequence with Claude automatically activating appropriate skills.

### Individual Skills

Skills activate automatically based on context:
- "Clarify requirements for X" → requirements-clarification
- "Explore how authentication works" → codebase-exploration
- "Design caching architecture" → architecture-design
- "Implement login feature" → code-implementation
- "Review my recent changes" → code-review

### Custom Workflows

Combine skills for specific scenarios:
- **Bug fix:** exploration → implementation → review
- **Refactoring:** exploration → design → implementation → review
- **Architecture only:** exploration → design
- **Quick implementation:** implementation → review

## Agents

The plugin includes 3 specialized agents used by the skills:

- **feature-skill:code-architect** - Designs architecture approaches
- **feature-skill:code-reviewer** - Reviews code quality
- **feature-skill:code-researcher** - Researches external resources

## Key Features

✅ **Modular** - Each skill works independently
✅ **Composable** - Skills combine automatically for complex workflows
✅ **Reusable** - Use skills across different projects
✅ **Quality-focused** - Systematic approach ensures thoroughness
✅ **User-guided** - Confirms before major transitions
✅ **Convention-aware** - Respects project patterns

## Skill Benefits

**vs Monolithic Command:**
- More flexible - use only what you need
- Better discovery - Claude activates right skill automatically
- Easier to maintain - update skills independently
- Shareable - skills work across projects

**vs Manual Process:**
- More systematic - no steps skipped
- More thorough - agent-powered exploration
- More consistent - follows proven workflow
- More efficient - parallel agent execution

## Version

1.0.0 - Initial release with 5 core skills

## License

MIT
