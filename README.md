# Inline Images

Sometimes ASCII art is not enough.

Sometimes an image says more than a thousand words.

This Sublime Text plugin can display images inline to improve your documentation.

![Example](https://user-images.githubusercontent.com/4941909/132251464-0f6c48b2-f6ca-4ef7-9c76-39a78fbdd67c.png)


## Usage

Use the `![alt text](uri)` markdown syntax inside *a single-line comment*.

E. g. in Python you would use

```
def hello():
   # ![](say_hello.png)
   print('Hello')
```

Local images are loaded by default, remote images (https://...) aren't.

You can configure an image's dimensions by adding HTML `<img>` properties after the image markup: `![alt text](uri){width="200", height="200"}`. Everything between the `{}` will be copied to the `<img>` element that renders the image.

## Installation

I hope that it will be on Package Control soon.

In the meantime, download the [latest release](https://github.com/haferburg/Sublime-Inline-Images/releases/new). In Sublime, select Preferences->Browse Packages..., then unzip the folder in the archive to that folder. Rename it to `Inline-Images`.

![image](https://user-images.githubusercontent.com/4941909/132352176-c1dc2f8e-27c1-4016-b23d-b108cbbb2d40.png)

## Configuration

Go to `Preferences -> Package Settings -> Inline Images`.

## Commands

* `Inline Images: Show All Images`
* `Inline Images: Show Remote Images`
* `Inline Images: Show Local Images`
* `Inline Images: Hide Images`

## Notes

Only PNG, JPG and GIF images are supported.

## Related

Plugins with similar functionality:

[ImagePreview](https://github.com/alvesjtiago/hover-preview)

[Markdown Images](https://github.com/xsleonard/sublime-MarkdownImages)

[Sublime ZK](https://github.com/renerocksai/sublime_zk)

## Credits 

This plugin is based on [Markdown Images](https://github.com/xsleonard/sublime-MarkdownImages).

