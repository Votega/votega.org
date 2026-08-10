# frozen_string_literal: true

source "https://rubygems.org"

# Windows and JRuby does not include zoneinfo files, so bundle the tzinfo-data gem
# and associated library.
platforms :mingw, :x64_mingw, :mswin, :jruby do
  gem "tzinfo", ">= 1", "< 3"
  gem "tzinfo-data"
end

# Performance-booster for watching directories on Windows
gem "wdm", "~> 0.1", :platforms => [:mingw, :x64_mingw, :mswin]

# Generates meta-refresh redirect stubs from `redirect_from` / `redirect_to`
# front matter. Part of the github-pages gem set used by the deploy workflow,
# so declaring it here keeps local `bundle exec jekyll` builds in parity.
gem "jekyll-redirect-from"

gemspec

