from dataclasses import dataclass
from pathlib import Path
from lib.plugin_config import PlatformConfig

@dataclass(frozen=True)
class XmlUpload:
    local_path: Path
    object_relative_path: str


def collect_xml_uploads(platforms: list[PlatformConfig]) -> list[XmlUpload]:
    uploads = []
    for platform in platforms:
        path = platform.path
        if not path.exists():
            raise FileNotFoundError(f"platform path does not exist: {path} (platform: {platform.name})")
            
        platform_uploads = []
        if path.is_file():
            # For single file, we use its name
            platform_uploads.append(XmlUpload(
                local_path=path,
                object_relative_path=f"{platform.name}/{path.name}"
            ))
        elif path.is_dir():
            # For directory, we recurse and keep relative structure
            xml_files = sorted(
                (p for p in path.rglob("*.xml") if p.is_file()),
                key=lambda p: p.relative_to(path).as_posix(),
            )
            for xml_file in xml_files:
                rel_path = xml_file.relative_to(path).as_posix()
                platform_uploads.append(XmlUpload(
                    local_path=xml_file,
                    object_relative_path=f"{platform.name}/{rel_path}"
                ))
        
        if not platform_uploads:
            raise ValueError(f"no JUnit XML files found for platform: {platform.name} at {path}")
            
        uploads.extend(platform_uploads)
        
    return uploads
