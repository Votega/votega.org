# Third-party notices

VoteGA.org's own source code is licensed under the PolyForm Noncommercial License
1.0.0 (see [LICENSE](LICENSE)). The components below are **not** covered by that
license. Each keeps the license its authors chose, and none has been relicensed.
Original license headers inside the vendored files must be left intact.

## Vendored in this repository

### Beautiful Jekyll theme

- Used for: the site's layouts, includes and base styling (`_layouts/`,
  `_includes/`, `assets/css/beautifuljekyll*.css`, `assets/js/beautifuljekyll.js`,
  `assets/js/staticman.js`, `assets/css/staticman.css`, `assets/css/pygment_highlights.css`,
  `beautiful-jekyll-theme.gemspec`, and related theme scaffolding).
- Source: https://github.com/daattali/beautiful-jekyll
- License: MIT

```
MIT License

Copyright (c) 2023 Dean Attali

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

VoteGA.org has modified some theme files. Those files remain derived from the
MIT-licensed theme, and the theme's copyright and permission notice above applies
to the theme's portions of them.

### Bootstrap Social

- File: `assets/css/bootstrap-social.css`
- Source: https://github.com/lipis/bootstrap-social
- Copyright 2013-2015 Panayiotis Lipiridis
- License: MIT (stated in the file's header, which must be kept)

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### ReadTime include

- File: `_includes/readtime.html`
- Copyright (c) 2020 Ruby Griffith Ramirez ("ReadTime on GitHub Jekyll")
- License: MIT (stated in the file's header, which must be kept)

## Loaded from third-party CDNs (not redistributed from this repository)

These are fetched by visitors' browsers from the CDN named, under the libraries'
own licenses. They are listed for transparency; their license headers travel with
the files the CDN serves.

| Component | Version | Loaded from | License |
|---|---|---|---|
| Bootstrap (CSS + JS) | 4.4.1 | cdnjs.cloudflare.com | MIT |
| jQuery (slim) | 3.5.1 | code.jquery.com | MIT |
| Popper.js | 1.16.0 | cdn.jsdelivr.net | MIT |
| Font Awesome Free | 6.5.2 | cdnjs.cloudflare.com | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT |
| Public Sans (web font) | n/a | fonts.googleapis.com | SIL Open Font License 1.1 |
| Simple-Jekyll-Search | latest | unpkg.com | MIT |

## Build-time tools (not distributed with the site)

Jekyll and its plugins (MIT) build the site. The data-generation scripts use
third-party Python packages such as PyYAML (MIT), Requests (Apache-2.0) and
Pillow (HPND) at build time. None is bundled in this repository or in the
published site.

## Media and data

Images, portraits and other media in `assets/img/` are not covered by the code
license. Government-published portraits come from the sources named on the pages
that use them; any other media remains the property of its respective owners.
Published data and site text are licensed separately (CC BY-SA 4.0); see
[NOTICE.md](NOTICE.md).
