# DeepWatch Design System

## Product

DeepWatch is an industrial subsea pipeline integrity monitoring platform.

It is NOT:
- a generic AI SaaS dashboard
- a crypto dashboard
- a developer portfolio
- a cyberpunk game UI

It SHOULD feel like:
- advanced offshore control-room software
- premium marine engineering software
- scientific instrumentation
- modern industrial HMI with restrained cinematic depth

The design must communicate:
TRUST
PRECISION
DEPTH
SAFETY
ENGINEERING

---

# Visual Direction

Primary inspiration:

1. Deep ocean photography
   - extreme depth
   - dark navy
   - faint blue atmospheric scattering
   - subtle volumetric light from above
   - quiet underwater movement

2. Infinity Signal
   Use ONLY for:
   - strong typography hierarchy
   - selective gradients
   - emphasis on critical numbers
   - premium spacing
   - visual confidence

3. Gustavo Batista
   Use ONLY for:
   - subtle environmental motion
   - cursor-responsive depth/parallax
   - atmospheric layering
   - immersive feeling

Do NOT imitate these websites literally.

Translate those ideas into industrial subsea monitoring software.

---

# Color System

Background:
#050B14

Deep ocean:
#071525
#09243A
#0B3550

Panel surface:
#0B1421
#0F1B2A

Borders:
rgba(105, 160, 200, 0.16)

Primary text:
#EAF4FC

Secondary text:
#8FA8BA

Muted text:
#607A8E

Technical blue:
#4AA8FF

Cyan emphasis:
#5DE4FF

Ice highlight:
#BCEEFF

Healthy:
muted green only

Caution:
amber

Degraded:
orange

Critical / alarm:
red

Red must ONLY appear for abnormal states.

---

# Gradient

Use gradients very selectively.

Primary numeric emphasis:

linear-gradient(
  90deg,
  #BCEEFF 0%,
  #5DE4FF 45%,
  #4AA8FF 100%
)

Never gradient:
- body copy
- every heading
- navigation
- normal telemetry labels

Gradient should indicate importance, not decoration.

---

# Typography

Avoid default SaaS typography.

Primary UI:
clean technical grotesk / geometric sans if already available.

Telemetry:
monospace.

Large result numbers:
strong, compact, precise.

Avoid excessive letter spacing.

Avoid ALL CAPS except:
CRITICAL
LEAK CONFIRMED
ALARM ACTIVE
ISOLATED
NORMAL

Prefer:
"NPW localization"

over:
"NPW LEAK LOCALIZATION"

---

# Layout

Desktop first.

Primary hierarchy:

1. System condition
2. Leak location
3. Pipeline visualization
4. t_in / t_out / delta_t
5. Adaptive signal quality
6. Response
7. Secondary AI / diagnostics

Main layout approximately:

70% operations canvas
30% information rail

Critical numbers must NEVER wrap.

No text may escape a card.

Avoid stacking many cards inside cards.

Use whitespace and separators instead of boxes everywhere.

---

# Pipeline Visualization

The pipeline should be the visual center of the product.

Default appearance:
dark steel / muted blue.

Healthy:
quiet.

Leak:
localized bright red/orange focal point.

Do NOT make every pipeline segment equally bright red.

The eye must immediately know WHERE the abnormality is.

Deep-sea atmosphere may exist behind the pipeline:
- faint haze
- subtle light shafts
- particulate motion
- gentle depth gradient

The atmosphere must NEVER reduce legibility.

---

# Motion

Motion should imply an underwater environment.

Cursor movement may slightly influence:
- distant particles
- haze
- volumetric lighting
- background depth layers

Maximum movement should be subtle.

Do NOT:
- move cards
- move telemetry text
- wobble the interface
- make controls float

Pipeline may have extremely subtle depth response.

Respect prefers-reduced-motion.

---

# Panels

Avoid generic rounded SaaS cards.

Use:
- subtle separators
- restrained 1px borders
- small corner radius
- slight tonal differences
- occasional inner highlight

Avoid:
- heavy glassmorphism
- giant shadows
- neon outlines
- gradients on every border

---

# Critical Metrics

These deserve strongest visual hierarchy:

Leak coordinate
Distance from inlet
Distance from outlet
Segment
t_in
t_out
delta_t
Severity

Adaptive Signal Quality should prominently show:

Baseline
Noise
Adaptive threshold
dP/dt
Signal state

AI corroboration is secondary.

---

# Interaction

Hover should provide engineering detail.

Clicking a pipeline segment should select it.

Leak marker should expose:
- coordinate
- inlet distance
- outlet distance
- segment
- timing

Important interactions should feel deliberate and restrained.

---

# Responsive Rules

Must be visually checked at:

1280 × 720
1440 × 900
1600 × 900
1920 × 1080

No clipping.
No overlapping.
No split value/unit.
No horizontal overflow.

---

# Absolute Rule

DeepWatch must look like:

"software an offshore pipeline integrity engineer might actually trust"

not:

"an AI-generated dashboard."