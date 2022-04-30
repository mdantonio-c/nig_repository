import {
  Component,
  OnInit,
  ChangeDetectionStrategy,
  Injector,
} from "@angular/core";
import { NgbActiveModal } from "@ng-bootstrap/ng-bootstrap";
import { AuthService } from "@rapydo/services/auth";
import { environment } from "@rapydo/../environments/environment";

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: "./download.modal.html",
})
export class DownloadModal implements OnInit {
  protected auth: AuthService;
  constructor(protected injector: Injector, public modal: NgbActiveModal) {
    this.auth = injector.get(AuthService);
  }

  fileFormats = ["bam", "g.vcf"];
  selectedFileformat;
  dataset: string;

  public ngOnInit(): void {
    this.selectedFileformat = "bam";
  }

  setFileFormat(fileFormat) {
    this.selectedFileformat = fileFormat;
  }

  private getFileURL() {
    const source_url = `${environment.backendURI}/api/dataset/${this.dataset}/download?file=${this.selectedFileformat}`;
    let token = this.auth.getToken();
    return source_url + "&access_token=" + token;
  }

  downloadFile() {
    // close the modal
    this.modal.close();
    // download the file
    const downloadUrl = this.getFileURL();
    let link = document.createElement("a");
    link.href = downloadUrl;
    link.download = `${this.dataset}.${this.selectedFileformat}`;
    link.style.visibility = "hidden";
    link.click();
  }
}
