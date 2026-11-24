# Apparel image eval: results

Cases evaluated: C03 of 10 planned. Models: `gpt-image-2.6-sunburst`. Reviewer: Claude (claude-opus-5-5), reading each output beside its inputs and the ground truth.

## 1. Summary

- Shape from the drawing is reproduced well: jacket, pleated skirt, flared sleeves, collar, jabot, cuffs and bloomers all follow the line drawing, and every velvet lattice trim lands where it was drawn.
- The fabric is recognisably the swatch's: same red ground, navy and green bands, cream and yellow overchecks, and a visible wool twill. Colour difference against the swatch is ΔE 2.5-3.2.
- Pattern scale runs slightly large: 6.0-7.3 repeats across the garment against 8.0 on the real suit, so the plaid is drawn about 10-25% too big.
- Where the drawing and swatch say nothing, the text decides: the case description wrongly said white bloomers, and all three samples made them white although the real ones are plaid. An error in the description goes straight into every image.
- The three samples are nearly identical in layout and differ mainly in plaid scale, so one sample would have given the same verdict here.
- Cost was $0.054 per image at medium quality, 1024x1536, in 23-28 seconds.

## 2. Test dataset

Each case starts from a public-domain museum photo of a real garment. The model gets a line drawing and a fabric swatch made from that photo; the photo itself is the ground truth and is never sent.

| Case | Task | Garment | Fabric | Ground truth | Source |
|---|---|---|---|---|---|
| C03 | T1 | child's two-piece suit: jacket and pleated skirt in the swatch fabric with black velvet ribbon lattice trims, worn over a white cotton blouse with eyelet lace collar, jabot and cuffs, and white bloomers | check / plaid | ground_truth/photo.jpg | The Met 159177 (Suit, ca. 1860, wool/cotton/silk, 2009.300.625a-c). The same photo also shows blouse 159178 (28.220), also public domain. |

Licences, authors and derivations for every file are in [data/SOURCES.csv](data/SOURCES.csv).

## 3. Method

| | |
|---|---|
| API | OpenAI `POST /v1/images/edits`, all inputs in one call |
| Models | `gpt-image-2.6-sunburst` |
| Settings | medium quality, 1024x1536 |
| Prompt | One template per task type, filled only from the case's item and scale fields; no per-case tuning in round 1 (templates in [data/manifest.json](data/manifest.json)) |
| Samples | 3 per case x model x variant. The API has no seed, so samples are independent draws |
| Variant A | line drawing + fabric swatch → product photo |
| Auto-checks | CIEDE2000 between the swatch's 4 dominant colours and the garment's; horizontal pattern repeat count by autocorrelation, compared with the ground truth's |
| Scoring | 1-5 on silhouette, fabric_pattern, pattern_scale, colour, texture, construction, usable_for_planning |

Input notes that affect the results:

- **C03**: Line drawing traced by the image model from the ground-truth photo (synthetic). Swatch crop has one pleat fold down the middle that shifts the pattern; no flat area holds a full repeat. Round 1 item text wrongly says white bloomers; the bloomers in the ground truth are the plaid fabric.

## 4. Results by case

Dashed grey frame = input, no frame = output, blue frame = ground truth.

### C03 · T1 · check / plaid

![C03](report/figures/C03.jpg)

**What worked**

- Silhouette and construction follow the drawing closely: cropped jacket with waistband and two buttons, knife-pleated skirt, three-quarter sleeves over lace cuffs, double collar and ruffled jabot.
- All nine velvet lattice trims are placed as drawn (two on the chest, two on the sleeves, five on the skirt), black and raised as described.
- The plaid carries the swatch's colour set and structure, including the pinkish slub stripes, and reads as wool twill. ΔE against the swatch is 2.5-3.2.
- Plaid is matched across the centre front of the jacket and runs continuously through the pleats.

**Issues**

- Plaid is drawn 10-25% too large (6.0-7.3 repeats across against 8.0 on the real suit). Sample 2 is the furthest off.
- Pleats are stiff, evenly pressed and shorter than the real skirt's soft, irregular, fuller pleats.
- Bloomers are white in every sample because the case description said so; the real bloomers are plaid. This is an error in the input text, not in the model.
- Blouse and lace are bright white where the original is aged cream. The prompt asked for a product photo of a new garment, so this is expected.

| Image | ΔE mean | ΔE max | Repeats across | vs ground truth |
|---|---|---|---|---|
| photo.jpg | 6.3 | 16.1 | 8.0 | 1.0 |
| A_r1_s1.png | 3.2 | 8.9 | 7.3 | 0.91 |
| A_r1_s2.png | 2.5 | 7.2 | 6.0 | 0.75 |
| A_r1_s3.png | 3.1 | 7.9 | 7.1 | 0.89 |

| Image | silhouette | fabric pattern | pattern scale | colour | texture | construction | usable for planning |
|---|---|---|---|---|---|---|---|
| A_r1_s1.png | 4 | 4 | 4 | 4 | 4 | 5 | 4 |
| A_r1_s2.png | 4 | 4 | 3 | 4 | 4 | 5 | 4 |
| A_r1_s3.png | 4 | 4 | 4 | 4 | 4 | 5 | 4 |
| **median** | 4 | 4 | 4 | 4 | 4 | 5 | 4 |

## 5. Cost and latency

Cost per call is computed from the response's `usage` tokens at standard-tier prices ($5 / 1M text input, $8 / 1M image input, $30 / 1M image output).

| Step | Model | Quality, size | Calls | Mean cost | Mean latency | Total |
|---|---|---|---|---|---|---|
| drawing trace | `gpt-image-2.6-sunburst` | high, 1024x1536 | 1 | $0.0538 | 35.1s | $0.054 |
| variant A, round 1 | `gpt-image-2.6-sunburst` | medium, 1024x1536 | 3 | $0.0538 | 25.0s | $0.161 |

Total spent: **$0.215**. Per-call rows are in [results/log.csv](results/log.csv).
