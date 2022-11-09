import {
  Component,
  OnInit,
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Injector,
} from "@angular/core";
import { HttpEventType } from "@angular/common/http";
import { NgbActiveModal } from "@ng-bootstrap/ng-bootstrap";
import { saveAs as importedSaveAs } from "file-saver-es";
import { NgxSpinnerService } from "ngx-spinner";
import { NotificationService } from "@rapydo/services/notification";
import { ApiService } from "@rapydo/services/api";
import { AuthService } from "@rapydo/services/auth";
import { environment } from "@rapydo/../environments/environment";

@Component({
  changeDetection: ChangeDetectionStrategy.OnPush,
  templateUrl: "./download.modal.html",
  styleUrls: ["./download.modal.scss"],
})
export class DownloadModal implements OnInit {
  protected auth: AuthService;
  constructor(
    protected injector: Injector,
    public modal: NgbActiveModal,
    private spinner: NgxSpinnerService,
    private api: ApiService,
    private notify: NotificationService,
    private cdr: ChangeDetectorRef
  ) {
    this.auth = injector.get(AuthService);
  }

  fileFormats = ["bam", "g.vcf"];
  selectedFileformat;
  dataset: string;
  download_endpoint: string;
  downloading: boolean = false;
  download_progress: number;
  downloaded_size: number;
  download_totalsize: number;

  public ngOnInit(): void {
    this.selectedFileformat = "bam";
    this.getDownloadURL();
    this.getTotalSize();
  }

  setFileFormat(fileFormat) {
    this.selectedFileformat = fileFormat;
    this.getDownloadURL();
    this.getTotalSize();
  }

  private getTotalSize() {
    const get_total_endpoint = `${this.download_endpoint}&get_total_size=true`;
    this.api.get<any>(get_total_endpoint).subscribe(
      (response) => {
        this.download_totalsize = response;
      },
      (error) => {
        this.notify.showError("Unable to get the filesize");
        this.download_totalsize = 0;
      }
    );
  }

  private getDownloadURL() {
    this.download_endpoint = `${environment.backendURI}/api/dataset/${this.dataset}/download?file=${this.selectedFileformat}`;
  }

  public downloadFile() {
    this.downloading = true;
    this.download_progress = 0;
    this.downloaded_size = 0;
    this.spinner.show("downloader");

    // download the file
    let options = {
      conf: {
        responseType: "blob",
        reportProgress: "true",
        observe: "events",
      },
    };

    const filename = `${this.dataset}.${this.selectedFileformat}`;

    console.log(`download total size : ${this.download_totalsize}`);

    this.api.get<any>(this.download_endpoint, {}, options).subscribe(
      (response) => {
        if (response.type === HttpEventType.DownloadProgress) {
          this.downloaded_size = Number(response.loaded);
          if (this.download_totalsize !== null && this.download_totalsize > 0) {
            let p = (100 * this.downloaded_size) / this.download_totalsize;
            this.download_progress = Math.round(p);
            this.cdr.detectChanges();
            //console.log(`${this.downloaded_size} / ${this.download_totalsize} = ${this.download_progress}`)
          }
        }

        if (response.type === HttpEventType.Response) {
          importedSaveAs(response.body, filename);
          this.downloading = false;
          this.spinner.hide("downloader");
          // close the modal
          this.modal.close();
        }
      },
      (error) => {
        this.downloading = false;
        this.spinner.hide("downloader");
        this.notify.showError("Unable to download file: " + filename);
        // close the modal
        this.modal.close();
      }
    );
  }
}
